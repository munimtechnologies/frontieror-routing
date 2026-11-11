"""gpshim: a small gurobipy-compatible modelling layer that solves with the open-source HiGHS solver.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization. Contains no Gurobi software: it re-implements the common
part of the gurobipy modelling API (Model, addVar/addVars, addConstr, quicksum, LinExpr, tupledict, GRB constants,
X/ObjVal/Status/...) in pure Python and hands the linear (mixed-integer) model to HiGHS through highspy, or to
scipy.optimize.milp (also HiGHS) when highspy is missing.

Use: put `sys.modules["gurobipy"] = gpshim` before running a script written for gurobipy, or `import gpshim as gp`.

Supported: continuous, binary, integer (and semi-continuous via HiGHS) variables; linear constraints (<=, >=, ==,
ranges); linear objectives with a constant; maximise/minimise; indicator constraints when the linear side has finite
bounds (rewritten as big-M); MIP starts (Var.Start) when highspy accepts them; LP duals (Constr.Pi, Var.RC) for pure
LPs; TimeLimit, MIPGap, Seed. Not supported (raise GurobiError, so a caller can fall back): quadratic terms,
callbacks, general constraints other than indicators, the matrix API (addMVar), multiple objectives, IIS.

A global deadline (set_deadline(epoch_seconds) or the MV2_GPSHIM_DEADLINE environment variable) caps every
optimize() call, whatever TimeLimit the script asks for. If MV2_GPSHIM_LOG names a file, each optimize() appends one
JSON line with the model size, sense, status and objective.
"""
import itertools
import json
import numbers
import os
import time

__version__ = "0.1.0"
INF = float("inf")
_DEADLINE = [None]
_STATS = []


def set_deadline(epoch_seconds):
    _DEADLINE[0] = None if epoch_seconds is None else float(epoch_seconds)


if os.environ.get("MV2_GPSHIM_DEADLINE"):
    try:
        set_deadline(float(os.environ["MV2_GPSHIM_DEADLINE"]))
    except ValueError:
        pass


class GurobiError(Exception):
    def __init__(self, *args):
        super().__init__(*args)
        self.errno = 10001
        self.message = str(args[0]) if args else ""


class _Names(type):
    """GRB.Param.X / GRB.Attr.X / GRB.param.X evaluate to the string 'X'."""

    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return name


class _Status:
    LOADED = 1
    OPTIMAL = 2
    INFEASIBLE = 3
    INF_OR_UNBD = 4
    UNBOUNDED = 5
    CUTOFF = 6
    ITERATION_LIMIT = 7
    NODE_LIMIT = 8
    TIME_LIMIT = 9
    SOLUTION_LIMIT = 10
    INTERRUPTED = 11
    NUMERIC = 12
    SUBOPTIMAL = 13
    INPROGRESS = 14
    USER_OBJ_LIMIT = 15
    WORK_LIMIT = 16
    MEM_LIMIT = 17


class GRB(_Status):
    BINARY = "B"
    INTEGER = "I"
    CONTINUOUS = "C"
    SEMICONT = "S"
    SEMIINT = "N"
    MINIMIZE = 1
    MAXIMIZE = -1
    INFINITY = 1e100
    UNDEFINED = 1e101
    LESS_EQUAL = "<"
    GREATER_EQUAL = ">"
    EQUAL = "="
    Status = _Status

    class Param(metaclass=_Names):
        pass

    class Attr(metaclass=_Names):
        pass

    param = Param
    attr = Attr

    class Callback:
        POLLING = 0
        PRESOLVE = 1
        SIMPLEX = 2
        MIP = 3
        MIPSOL = 4
        MIPNODE = 5
        MESSAGE = 6
        BARRIER = 7
        MULTIOBJ = 8
        MIPSOL_SOL = 4001
        MIPSOL_OBJ = 4002
        MIPSOL_OBJBST = 4003
        MIPSOL_OBJBND = 4004
        MIPNODE_STATUS = 5001
        MIP_OBJBST = 3000
        MIP_OBJBND = 3001
        RUNTIME = 6002

    callback = Callback


def _num(o):
    return isinstance(o, numbers.Number) and not isinstance(o, complex)


def _big(v):
    return v is None or v >= 1e30


class _Expr:
    __array_ufunc__ = None  # let numpy scalars defer to our reflected operators
    __hash__ = object.__hash__

    def __le__(self, o):
        return TempConstr(self, GRB.LESS_EQUAL, o)

    def __ge__(self, o):
        return TempConstr(self, GRB.GREATER_EQUAL, o)

    def __eq__(self, o):
        return TempConstr(self, GRB.EQUAL, o)

    def __add__(self, o):
        e = LinExpr(self)
        return e._iadd(o, 1.0)

    def __radd__(self, o):
        e = LinExpr(self)
        return e._iadd(o, 1.0)

    def __sub__(self, o):
        e = LinExpr(self)
        return e._iadd(o, -1.0)

    def __rsub__(self, o):
        e = LinExpr(self)._scale(-1.0)
        return e._iadd(o, 1.0)

    def __neg__(self):
        return LinExpr(self)._scale(-1.0)

    def __pos__(self):
        return LinExpr(self)

    def __mul__(self, o):
        if _num(o):
            return LinExpr(self)._scale(float(o))
        if isinstance(o, LinExpr) and not o.t:
            return LinExpr(self)._scale(o.c)
        if isinstance(self, LinExpr) and not self.t and isinstance(o, _Expr):
            return LinExpr(o)._scale(self.c)
        if isinstance(o, _Expr):
            raise GurobiError("gpshim: quadratic expressions are not supported")
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, o):
        if _num(o):
            return LinExpr(self)._scale(1.0 / float(o))
        if isinstance(o, LinExpr) and not o.t:
            return LinExpr(self)._scale(1.0 / o.c)
        raise GurobiError("gpshim: division by an expression is not supported")

    def __pow__(self, k):
        if k == 1:
            return LinExpr(self)
        if k == 0:
            return LinExpr(1.0)
        raise GurobiError("gpshim: quadratic expressions are not supported")


class Var(_Expr):
    """A model variable. Attributes are case-insensitive as in gurobipy (X/x, LB/lb, ...)."""

    def __init__(self, model, lb, ub, obj, vtype, name):
        object.__setattr__(self, "_m", model)
        object.__setattr__(self, "_lb", float(lb) if lb is not None else 0.0)
        object.__setattr__(self, "_ub", INF if _big(ub) else float(ub))
        object.__setattr__(self, "_obj", float(obj or 0.0))
        object.__setattr__(self, "_vt", str(vtype or "C").upper()[:1])
        object.__setattr__(self, "_name", name or "")
        object.__setattr__(self, "_x", None)
        object.__setattr__(self, "_rc", None)
        object.__setattr__(self, "_start", None)
        object.__setattr__(self, "_idx", -1)
        object.__setattr__(self, "_removed", False)

    def __repr__(self):
        return "<gpshim.Var %s>" % (self._name or "C%d" % self._idx)

    def __getattr__(self, name):
        k = name.lower()
        if k == "x":
            if self._x is None:
                raise GurobiError("Unable to retrieve attribute 'X'")
            return self._x
        if k == "lb":
            return self._lb
        if k == "ub":
            return GRB.INFINITY if self._ub == INF else self._ub
        if k == "obj":
            return self._obj
        if k == "vtype":
            return self._vt
        if k == "varname":
            return self._name
        if k == "start":
            return GRB.UNDEFINED if self._start is None else self._start
        if k == "rc":
            if self._rc is None:
                raise GurobiError("Unable to retrieve attribute 'RC'")
            return self._rc
        if k == "index":
            return self._idx
        if k in ("varhintval", "varhintpri", "branchpriority", "partition", "poolignore"):
            return 0
        raise AttributeError(name)

    def __setattr__(self, name, value):
        k = name.lower()
        if k == "lb":
            object.__setattr__(self, "_lb", -INF if value is not None and value <= -1e30 else float(value))
        elif k == "ub":
            object.__setattr__(self, "_ub", INF if _big(value) else float(value))
        elif k == "obj":
            object.__setattr__(self, "_obj", float(value))
        elif k == "vtype":
            object.__setattr__(self, "_vt", str(value).upper()[:1])
        elif k == "varname":
            object.__setattr__(self, "_name", str(value))
        elif k == "start":
            object.__setattr__(self, "_start", None if value is None or value >= 1e100 else float(value))
        elif k in ("varhintval", "varhintpri", "branchpriority", "partition", "poolignore"):
            pass
        else:
            raise AttributeError("gpshim: cannot set Var attribute %r" % name)

    def getAttr(self, name):
        return getattr(self, name)

    def setAttr(self, name, value):
        setattr(self, name, value)

    def sameAs(self, other):
        return self is other

    def getValue(self):
        return self.X


class LinExpr(_Expr):
    __slots__ = ("t", "c")

    def __init__(self, arg1=0.0, arg2=None):
        self.t = {}
        self.c = 0.0
        if arg2 is not None:
            if isinstance(arg2, Var):
                self.t[arg2] = float(arg1)
            else:
                for a, v in zip(arg1, arg2):
                    self.t[v] = self.t.get(v, 0.0) + float(a)
        elif isinstance(arg1, Var):
            self.t[arg1] = 1.0
        elif isinstance(arg1, LinExpr):
            self.t = dict(arg1.t)
            self.c = arg1.c
        elif isinstance(arg1, (list, tuple)):
            for a, v in arg1:
                self.t[v] = self.t.get(v, 0.0) + float(a)
        elif _num(arg1):
            self.c = float(arg1)
        else:
            raise GurobiError("gpshim: cannot build LinExpr from %r" % (type(arg1),))

    def __repr__(self):
        return "<gpshim.LinExpr %d terms + %g>" % (len(self.t), self.c)

    def _scale(self, s):
        if s != 1.0:
            for v in self.t:
                self.t[v] *= s
            self.c *= s
        return self

    def _iadd(self, o, s):
        if isinstance(o, Var):
            self.t[o] = self.t.get(o, 0.0) + s
        elif isinstance(o, LinExpr):
            t = self.t
            for v, a in o.t.items():
                t[v] = t.get(v, 0.0) + s * a
            self.c += s * o.c
        elif _num(o):
            self.c += s * float(o)
        elif isinstance(o, QuadExpr):
            raise GurobiError("gpshim: quadratic expressions are not supported")
        else:
            return NotImplemented
        return self

    def __iadd__(self, o):
        return self._iadd(o, 1.0)

    def __isub__(self, o):
        return self._iadd(o, -1.0)

    def __imul__(self, o):
        if _num(o):
            return self._scale(float(o))
        return self * o

    def add(self, expr, mult=1.0):
        self._iadd(expr, float(mult))

    def addTerms(self, coeffs, vars_):
        if isinstance(vars_, Var):
            self.t[vars_] = self.t.get(vars_, 0.0) + float(coeffs)
            return
        for a, v in zip(coeffs, vars_):
            self.t[v] = self.t.get(v, 0.0) + float(a)

    def addConstant(self, c):
        self.c += float(c)

    def getConstant(self):
        return self.c

    def size(self):
        return len(self.t)

    def getVar(self, i):
        return list(self.t.keys())[i]

    def getCoeff(self, i):
        return list(self.t.values())[i]

    def remove(self, item):
        if isinstance(item, Var):
            self.t.pop(item, None)
        else:
            k = list(self.t.keys())[int(item)]
            self.t.pop(k, None)

    def clear(self):
        self.t = {}
        self.c = 0.0

    def copy(self):
        return LinExpr(self)

    def getValue(self):
        return self.c + sum(a * v.X for v, a in self.t.items())


class QuadExpr:
    def __init__(self, *a, **k):
        raise GurobiError("gpshim: quadratic expressions are not supported")


class TempConstr:
    __array_ufunc__ = None

    def __init__(self, lhs, sense, rhs):
        e = LinExpr(lhs) if isinstance(lhs, _Expr) else LinExpr(float(lhs))
        if isinstance(rhs, (list, tuple)) and len(rhs) == 2 and sense == GRB.EQUAL:  # expr == [lb, ub]
            self.expr, self.sense, self.lo, self.hi = e, "R", float(rhs[0]), float(rhs[1])
            return
        if isinstance(rhs, _Expr):
            e._iadd(rhs, -1.0)
        elif _num(rhs):
            e.c -= float(rhs)
        else:
            raise GurobiError("gpshim: bad right-hand side %r" % (type(rhs),))
        self.expr, self.sense = e, sense
        self.lo = self.hi = None

    def __rshift__(self, other):  # (b == 1) >> (expr <= c): indicator
        return _Indicator(self, other)

    def __bool__(self):  # Python chains like a <= x <= b are not supported, as in gurobipy
        raise GurobiError("gpshim: constraint used as a truth value")


class _Indicator:
    def __init__(self, cond, con):
        self.cond, self.con = cond, con


class Column:
    def __init__(self, coeffs=None, constrs=None):
        self.pairs = []
        if coeffs is None:
            return
        if isinstance(constrs, Constr):
            self.pairs.append((float(coeffs), constrs))
        else:
            for a, c in zip(coeffs, constrs):
                self.pairs.append((float(a), c))

    def addTerms(self, coeffs, constrs):
        if isinstance(constrs, Constr):
            self.pairs.append((float(coeffs), constrs))
        else:
            for a, c in zip(coeffs, constrs):
                self.pairs.append((float(a), c))

    def size(self):
        return len(self.pairs)


class Constr:
    def __init__(self, model, expr, sense, rhs, name, lo=None, hi=None):
        self._m = model
        self._t = dict(expr.t)  # Var -> coefficient (constant already moved into rhs)
        self._sense = sense
        self._rhs = float(rhs)
        self._lo, self._hi = lo, hi
        self._name = name or ""
        self._pi = None
        self._slack = None
        self._idx = -1
        self._removed = False

    def __repr__(self):
        return "<gpshim.Constr %s>" % (self._name or "R%d" % self._idx)

    def __getattr__(self, name):
        k = name.lower()
        if k == "pi":
            if self._pi is None:
                raise GurobiError("Unable to retrieve attribute 'Pi'")
            return self._pi
        if k == "slack":
            if self._slack is None:
                raise GurobiError("Unable to retrieve attribute 'Slack'")
            return self._slack
        if k == "rhs":
            return self._rhs
        if k == "sense":
            return self._sense
        if k == "constrname":
            return self._name
        if k == "index":
            return self._idx
        if k in ("lazy",):
            return 0
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        k = name.lower()
        if k == "rhs":
            self._rhs = float(value)
        elif k == "sense":
            self._sense = value
        elif k == "constrname":
            self._name = str(value)
        elif k == "lazy":
            pass
        else:
            raise AttributeError("gpshim: cannot set Constr attribute %r" % name)

    def getAttr(self, name):
        return getattr(self, name)

    def setAttr(self, name, value):
        setattr(self, name, value)


def _match(key, pattern):
    if not isinstance(key, tuple):
        key = (key,)
    if len(pattern) != len(key):
        return False
    return all(p == "*" or p == k for p, k in zip(pattern, key))


class tupledict(dict):
    def select(self, *pattern):
        if not pattern:
            return list(self.values())
        return [v for k, v in self.items() if _match(k, pattern)]

    def sum(self, *pattern):
        e = LinExpr()
        for v in (self.select(*pattern) if pattern else self.values()):
            e._iadd(v, 1.0)
        return e

    def prod(self, coeff, *pattern):
        e = LinExpr()
        for k, v in self.items():
            if pattern and not _match(k, pattern):
                continue
            if k in coeff:
                e._iadd(v * coeff[k], 1.0)
        return e


class tuplelist(list):
    def select(self, *pattern):
        return tuplelist(k for k in self if _match(k, pattern))


def multidict(data):
    keys = list(data.keys())
    first = next(iter(data.values()), None)
    if isinstance(first, (list, tuple)):
        n = len(first)
        dicts = [dict() for _ in range(n)]
        for k, vals in data.items():
            for i in range(n):
                dicts[i][k] = vals[i]
        return [tuplelist(keys)] + dicts
    return [tuplelist(keys), dict(data)]


def quicksum(items):
    e = LinExpr()
    for it in items:
        if e._iadd(it, 1.0) is NotImplemented:
            raise GurobiError("gpshim: cannot add %r to an expression" % (type(it),))
    return e


def _unsupported(what):
    def f(*a, **k):
        raise GurobiError("gpshim: %s is not supported" % what)
    return f


max_ = _unsupported("max_")
min_ = _unsupported("min_")
abs_ = _unsupported("abs_")
and_ = _unsupported("and_")
or_ = _unsupported("or_")
norm = _unsupported("norm")


class Env:
    def __init__(self, logfilename="", empty=False, params=None):
        self.params = dict(params or {})

    def setParam(self, name, value):
        self.params[name] = value

    def start(self):
        return self

    def dispose(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def disposeDefaultEnv():
    pass


def setParam(name, value):  # gurobipy.setParam: default-environment parameter
    _GLOBAL_PARAMS[str(name).lower()] = value


_GLOBAL_PARAMS = {}


class _Params:
    def __init__(self, base=None):
        object.__setattr__(self, "_p", dict(_GLOBAL_PARAMS))
        if base:
            for k, v in base.items():
                self._p[str(k).lower()] = v

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._p.get(name.lower(), _PARAM_DEFAULTS.get(name.lower(), 0))

    def __setattr__(self, name, value):
        self._p[name.lower()] = value

    def _get(self, name, default=None):
        return self._p.get(name.lower(), default)


_PARAM_DEFAULTS = {"timelimit": INF, "mipgap": 1e-4, "outputflag": 1, "threads": 0, "seed": 0}


def _vtype_list(vtype, keys):
    return vtype


def _per_key(val, key, pos):
    if isinstance(val, dict):
        return val[key]
    if isinstance(val, (list, tuple)):
        return val[pos]
    try:
        import numpy as _np
        if isinstance(val, _np.ndarray):
            return val.flat[pos]
    except ImportError:
        pass
    return val


class Model:
    def __init__(self, name="", env=None):
        # internal names start with _gp so that user attributes such as model._vars (callback data) never clash
        object.__setattr__(self, "_gpv", [])
        object.__setattr__(self, "_gpc", [])
        object.__setattr__(self, "_gpi", [])
        object.__setattr__(self, "_gpo", 0.0)
        object.__setattr__(self, "_gps", GRB.MINIMIZE)
        object.__setattr__(self, "Params", _Params(getattr(env, "params", None)))
        object.__setattr__(self, "_gpr", {"Status": GRB.LOADED, "SolCount": 0, "ObjVal": None, "ObjBound": None,
                                          "MIPGap": None, "Runtime": 0.0, "NodeCount": 0, "IterCount": 0})
        object.__setattr__(self, "ModelName", name)

    params = property(lambda self: self.Params)

    # ---------------------------------------------------------------- attributes
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        k = name.lower()
        res = self._gpr
        if k == "status":
            return res["Status"]
        if k == "solcount":
            return res["SolCount"]
        if k in ("objval", "poolobjval"):
            if not res["SolCount"]:
                raise GurobiError("Unable to retrieve attribute 'ObjVal'")
            return res["ObjVal"]
        if k in ("objbound", "objboundc"):
            if res["ObjBound"] is None:
                raise GurobiError("Unable to retrieve attribute 'ObjBound'")
            return res["ObjBound"]
        if k == "mipgap":
            if res["MIPGap"] is None:
                raise GurobiError("Unable to retrieve attribute 'MIPGap'")
            return res["MIPGap"]
        if k == "runtime":
            return res["Runtime"]
        if k == "nodecount":
            return res["NodeCount"]
        if k in ("itercount", "baritercount"):
            return res["IterCount"]
        if k == "numvars":
            return len(self._live_vars())
        if k == "numconstrs":
            return len(self._live_cons())
        if k == "numintvars":
            return sum(1 for v in self._live_vars() if v._vt in "BIN")
        if k == "numbinvars":
            return sum(1 for v in self._live_vars() if v._vt == "B")
        if k == "ismip":
            return int(any(v._vt in "BIN" for v in self._live_vars()) or bool(self._gpi))
        if k == "modelsense":
            return self._gps
        if k == "objcon":
            return self._gpo
        if k == "numnzs":
            return sum(len(c._t) for c in self._live_cons())
        if k in ("numqconstrs", "numsos", "numgenconstrs", "numqnzs", "numobj"):
            return 0 if k != "numgenconstrs" else len(self._gpi)
        if k == "modelname":
            return object.__getattribute__(self, "ModelName")
        raise AttributeError(name)

    def __setattr__(self, name, value):
        k = name.lower()
        if k == "modelsense":
            object.__setattr__(self, "_gps", int(value))
        elif k == "objcon":
            object.__setattr__(self, "_gpo", float(value))
        elif k == "modelname":
            object.__setattr__(self, "ModelName", value)
        elif name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            raise AttributeError("gpshim: cannot set Model attribute %r" % name)

    def setParam(self, name, value):
        setattr(self.Params, str(name), value)

    def getParamInfo(self, name):
        v = getattr(self.Params, str(name))
        return (str(name), type(v), v, v, v, v)

    def getAttr(self, attr, objs=None):
        if objs is None:
            return getattr(self, attr)
        if isinstance(objs, dict):
            return {k: getattr(v, attr) for k, v in objs.items()}
        return [getattr(o, attr) for o in objs]

    def setAttr(self, attr, objs, vals=None):
        if vals is None:
            setattr(self, attr, objs)
            return
        if isinstance(objs, dict):
            for k, o in objs.items():
                setattr(o, attr, vals[k] if isinstance(vals, dict) else vals)
            return
        if _num(vals):
            for o in objs:
                setattr(o, attr, vals)
            return
        for o, v in zip(objs, vals):
            setattr(o, attr, v)

    # ---------------------------------------------------------------- building
    def addVar(self, lb=0.0, ub=GRB.INFINITY, obj=0.0, vtype=GRB.CONTINUOUS, name="", column=None):
        if lb is not None and lb <= -1e30:
            lb = -INF
        v = Var(self, lb, ub, obj, vtype, name)
        self._gpv.append(v)
        if column is not None:
            for a, c in column.pairs:
                c._t[v] = c._t.get(v, 0.0) + a
        return v

    def addVars(self, *indices, lb=0.0, ub=GRB.INFINITY, obj=0.0, vtype=GRB.CONTINUOUS, name=""):
        keys = _keys(indices)
        out = tupledict()
        for pos, k in enumerate(keys):
            if isinstance(name, str):
                nm = ("%s[%s]" % (name, ",".join(str(x) for x in (k if isinstance(k, tuple) else (k,))))
                      if name else "")
            else:
                nm = _per_key(name, k, pos)
            out[k] = self.addVar(lb=_per_key(lb, k, pos), ub=_per_key(ub, k, pos), obj=_per_key(obj, k, pos),
                                 vtype=_per_key(vtype, k, pos), name=nm)
        return out

    def _add_temp(self, tc, name):
        if isinstance(tc, _Indicator):
            return self._add_indicator(tc, name)
        if isinstance(tc, bool):
            if not tc:
                raise GurobiError("gpshim: constraint is constantly False")
            return None
        if not isinstance(tc, TempConstr):
            raise GurobiError("gpshim: unsupported constraint type %r" % (type(tc),))
        if tc.sense == "R":
            c = Constr(self, tc.expr, "R", 0.0, name, lo=tc.lo - tc.expr.c, hi=tc.hi - tc.expr.c)
        else:
            c = Constr(self, tc.expr, tc.sense, -tc.expr.c, name)
        self._gpc.append(c)
        return c

    def addConstr(self, constr, sense=None, rhs=None, name=""):
        if sense is not None and rhs is not None:  # old style addConstr(lhs, sense, rhs, name)
            constr = TempConstr(constr, _sense_of(sense), rhs)
        elif sense is not None and rhs is None and isinstance(sense, str) and not name:
            name = sense  # addConstr(tc, "name") positional
        return self._add_temp(constr, name)

    addLConstr = addConstr

    def addConstrs(self, gen, name=""):
        out = tupledict()
        for i, tc in enumerate(gen):
            c = self._add_temp(tc, "%s[%d]" % (name, i) if name else "")
            out[i] = c
        return out

    def addRange(self, expr, lower, upper, name=""):
        e = LinExpr(expr)
        c = Constr(self, e, "R", 0.0, name, lo=float(lower) - e.c, hi=float(upper) - e.c)
        self._gpc.append(c)
        return c

    def addGenConstrIndicator(self, binvar, binval, lhs, sense=None, rhs=None, name=""):
        tc = lhs if sense is None else TempConstr(lhs, _sense_of(sense), rhs)
        cond = TempConstr(binvar, GRB.EQUAL, float(binval))
        return self._add_indicator(_Indicator(cond, tc), name)

    def _add_indicator(self, ind, name):
        cond, tc = ind.cond, ind.con
        terms = [(v, a) for v, a in cond.expr.t.items()]
        if len(terms) != 1 or cond.sense != GRB.EQUAL or abs(terms[0][1] - 1.0) > 1e-12:
            raise GurobiError("gpshim: indicator must be (binvar == 0/1) >> (linear constraint)")
        b = terms[0][0]
        val = -cond.expr.c  # binvar == val
        if not isinstance(tc, TempConstr) or tc.sense == "R":
            raise GurobiError("gpshim: unsupported indicator body")
        # expression f = tc.expr (constant included), constraint f <=/>=/== 0 when b == val
        lo, hi = tc.expr.c, tc.expr.c
        for v, a in tc.expr.t.items():
            if a > 0:
                lo += a * v._lb
                hi += a * v._ub
            else:
                lo += a * v._ub
                hi += a * v._lb
        z = LinExpr(b) if val >= 0.5 else LinExpr(1.0) - b  # z = 1 when the indicator is active
        made = []
        if tc.sense in (GRB.LESS_EQUAL, GRB.EQUAL):
            if hi == INF:
                raise GurobiError("gpshim: indicator needs finite variable bounds (big-M)")
            if hi > 0:  # f <= hi * (1 - z)
                made.append(self._add_temp(tc.expr + hi * z <= hi, name))
        if tc.sense in (GRB.GREATER_EQUAL, GRB.EQUAL):
            if lo == -INF:
                raise GurobiError("gpshim: indicator needs finite variable bounds (big-M)")
            if lo < 0:  # f >= lo * (1 - z)
                made.append(self._add_temp(tc.expr + lo * z >= lo, name))
        self._gpi.append(made)
        return made[0] if len(made) == 1 else made

    def addMVar(self, *a, **k):
        raise GurobiError("gpshim: the matrix API (addMVar) is not supported")

    addMConstr = addMVar
    addQConstr = _unsupported("addQConstr")
    addSOS = _unsupported("addSOS")
    setObjectiveN = _unsupported("setObjectiveN")
    setPWLObj = _unsupported("setPWLObj")
    addGenConstrMax = _unsupported("addGenConstrMax")
    addGenConstrMin = _unsupported("addGenConstrMin")
    addGenConstrAbs = _unsupported("addGenConstrAbs")
    addGenConstrAnd = _unsupported("addGenConstrAnd")
    addGenConstrOr = _unsupported("addGenConstrOr")
    addGenConstrPWL = _unsupported("addGenConstrPWL")
    computeIIS = _unsupported("computeIIS")
    cbLazy = _unsupported("callbacks")
    cbCut = _unsupported("callbacks")
    cbGet = _unsupported("callbacks")
    cbGetSolution = _unsupported("callbacks")
    cbGetNodeRel = _unsupported("callbacks")
    cbSetSolution = _unsupported("callbacks")

    def setObjective(self, expr, sense=None):
        e = LinExpr(expr) if isinstance(expr, _Expr) else LinExpr(float(expr))
        for v in self._gpv:
            object.__setattr__(v, "_obj", 0.0)
        for v, a in e.t.items():
            object.__setattr__(v, "_obj", v._obj + a)
        object.__setattr__(self, "_gpo", e.c)
        if sense is not None:
            object.__setattr__(self, "_gps", int(sense))

    def getObjective(self):
        e = LinExpr(self._gpo)
        for v in self._gpv:
            if v._obj and not v._removed:
                e.t[v] = v._obj
        return e

    def getVars(self):
        return self._live_vars()

    def getConstrs(self):
        return self._live_cons()

    def getVarByName(self, name):
        for v in self._gpv:
            if v._name == name and not v._removed:
                return v
        return None

    def getConstrByName(self, name):
        for c in self._gpc:
            if c._name == name and not c._removed:
                return c
        return None

    def getRow(self, constr):
        return LinExpr(list(constr._t.values()), list(constr._t.keys()))

    def getCol(self, var):
        col = Column()
        for c in self._live_cons():
            if var in c._t:
                col.pairs.append((c._t[var], c))
        return col

    def getCoeff(self, constr, var):
        return constr._t.get(var, 0.0)

    def chgCoeff(self, constr, var, val):
        if val == 0:
            constr._t.pop(var, None)
        else:
            constr._t[var] = float(val)

    def remove(self, items):
        if isinstance(items, (Var, Constr)):
            items = [items]
        elif isinstance(items, dict):
            items = list(items.values())
        for it in items:
            if isinstance(it, (Var, Constr)):
                object.__setattr__(it, "_removed", True)

    def _live_vars(self):
        return [v for v in self._gpv if not v._removed]

    def _live_cons(self):
        return [c for c in self._gpc if not c._removed]

    def update(self):
        pass

    def reset(self, clearall=0):
        self._gpr.update(Status=GRB.LOADED, SolCount=0, ObjVal=None, ObjBound=None, MIPGap=None)

    def dispose(self):
        pass

    def terminate(self):
        pass

    def write(self, path):
        pass

    def printStats(self):
        pass

    def tune(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def relax(self):
        r, vmap = self._clone()
        for v in r._gpv:
            if v._vt in "BIN":
                if v._vt == "B":
                    object.__setattr__(v, "_lb", max(v._lb, 0.0))
                    object.__setattr__(v, "_ub", min(v._ub, 1.0))
                object.__setattr__(v, "_vt", "C")
        return r

    def copy(self):
        return self._clone()[0]

    def _clone(self):
        r = Model(self.ModelName)
        r.Params._p.update(self.Params._p)
        vmap = {}
        for v in self._live_vars():
            nv = r.addVar(lb=v._lb, ub=v._ub, obj=v._obj, vtype=v._vt, name=v._name)
            nv.Start = v._start if v._start is not None else GRB.UNDEFINED
            vmap[v] = nv
        for c in self._live_cons():
            nc = Constr(r, LinExpr(), c._sense, c._rhs, c._name, lo=c._lo, hi=c._hi)
            nc._t = {vmap[v]: a for v, a in c._t.items() if v in vmap}
            r._gpc.append(nc)
        object.__setattr__(r, "_gpo", self._gpo)
        object.__setattr__(r, "_gps", self._gps)
        return r, vmap

    # ---------------------------------------------------------------- solving
    def optimize(self, callback=None):
        if callback is not None:
            raise GurobiError("gpshim: callbacks are not supported")
        t0 = time.time()
        V = self._live_vars()
        for i, v in enumerate(V):
            object.__setattr__(v, "_idx", i)
            object.__setattr__(v, "_x", None)
            object.__setattr__(v, "_rc", None)
        C = self._live_cons()
        n, m = len(V), len(C)
        cost = [v._obj for v in V]
        lb, ub, integ = [], [], []
        for v in V:
            lo, hi = v._lb, v._ub
            if v._vt == "B":
                lo, hi = max(lo, 0.0), min(hi, 1.0)
            lb.append(lo)
            ub.append(hi)
            integ.append(v._vt)
        rlo, rhi, rows, cols, vals = [], [], [], [], []
        for r, c in enumerate(C):
            c._idx = r
            c._pi = None
            c._slack = None
            if c._sense == GRB.LESS_EQUAL:
                rlo.append(-INF)
                rhi.append(c._rhs)
            elif c._sense == GRB.GREATER_EQUAL:
                rlo.append(c._rhs)
                rhi.append(INF)
            elif c._sense == GRB.EQUAL:
                rlo.append(c._rhs)
                rhi.append(c._rhs)
            else:
                rlo.append(c._lo if c._lo is not None else -INF)
                rhi.append(c._hi if c._hi is not None else INF)
            for v, a in c._t.items():
                if a != 0.0 and not v._removed and v._m is self:
                    rows.append(r)
                    cols.append(v._idx)
                    vals.append(a)
        limit = self.Params._get("timelimit", INF)
        limit = INF if limit is None else float(limit)
        if _DEADLINE[0] is not None:
            limit = min(limit, _DEADLINE[0] - time.time())
        limit = max(0.5, limit)
        gap = self.Params._get("mipgap", 1e-4)
        seed = self.Params._get("seed", None)
        is_mip = any(t in "BINS" for t in integ)
        starts = [v._start for v in V]
        res = None
        try:
            import highspy  # noqa: F401
            have_highspy = True
        except Exception:  # noqa: BLE001
            have_highspy = False
        if have_highspy:
            res = _solve_highspy(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, self._gps, self._gpo,
                                 limit, gap, seed, starts)
        else:
            res = _solve_scipy(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, self._gps, self._gpo,
                               limit, gap)
        x = res.get("x")
        if x is not None:
            for v, xv in zip(V, x):
                object.__setattr__(v, "_x", float(xv))
            if res.get("row_value") is not None:
                for c, rv in zip(C, res["row_value"]):
                    if c._sense == GRB.LESS_EQUAL:
                        c._slack = c._rhs - rv
                    elif c._sense == GRB.GREATER_EQUAL:
                        c._slack = c._rhs - rv
                    else:
                        c._slack = 0.0 if c._sense == GRB.EQUAL else None
        if not is_mip and res.get("row_dual") is not None and x is not None:
            for c, d in zip(C, res["row_dual"]):
                c._pi = float(d)
            for v, d in zip(V, res.get("col_dual") or []):
                object.__setattr__(v, "_rc", float(d))
        rt = time.time() - t0
        self._gpr.update(Status=res["status"], SolCount=1 if x is not None else 0, ObjVal=res.get("obj"),
                         ObjBound=res.get("bound"), MIPGap=res.get("gap"), Runtime=rt,
                         NodeCount=res.get("nodes", 0), IterCount=res.get("iters", 0))
        _STATS.append({"vars": n, "constrs": m, "nnz": len(vals), "mip": is_mip,
                       "sense": "max" if self._gps == GRB.MAXIMIZE else "min", "status": res["status"],
                       "obj": res.get("obj"), "bound": res.get("bound"), "time_limit": round(limit, 3),
                       "runtime": round(rt, 3), "backend": res.get("backend"), "note": res.get("note")})
        p = os.environ.get("MV2_GPSHIM_LOG")
        if p:
            try:
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(_STATS[-1], default=str) + "\n")
            except OSError:
                pass


def _sense_of(s):
    s = str(s)
    if s in ("<", "<=", "L"):
        return GRB.LESS_EQUAL
    if s in (">", ">=", "G"):
        return GRB.GREATER_EQUAL
    return GRB.EQUAL


def _keys(indices):
    if not indices:
        return []
    lists = []
    for ix in indices:
        if isinstance(ix, numbers.Integral):
            lists.append(list(range(int(ix))))
        else:
            lists.append(list(ix))
    if len(lists) == 1:
        return lists[0]
    out = []
    for combo in itertools.product(*lists):
        k = []
        for part in combo:
            if isinstance(part, tuple):
                k.extend(part)
            else:
                k.append(part)
        out.append(tuple(k))
    return out


def _clean(b, default):
    return default if b is None else (INF if b >= 1e30 else (-INF if b <= -1e30 else float(b)))


def _solve_highspy(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, sense, objcon, limit, gap, seed,
                   starts):
    import highspy
    import numpy as np
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(limit))
    try:
        h.setOptionValue("mip_rel_gap", float(gap))
    except Exception:  # noqa: BLE001
        pass
    if seed is not None:
        try:
            h.setOptionValue("random_seed", int(seed))
        except Exception:  # noqa: BLE001
            pass
    inf = highspy.kHighsInf
    lp = highspy.HighsLp()
    lp.num_col_ = n
    lp.num_row_ = m
    lp.col_cost_ = np.array(cost, dtype=float)
    lp.col_lower_ = np.array([(-inf if v == -INF else v) for v in lb], dtype=float)
    lp.col_upper_ = np.array([(inf if v == INF else v) for v in ub], dtype=float)
    lp.row_lower_ = np.array([(-inf if v == -INF else v) for v in rlo], dtype=float)
    lp.row_upper_ = np.array([(inf if v == INF else v) for v in rhi], dtype=float)
    lp.offset_ = float(objcon)
    if sense == GRB.MAXIMIZE:
        lp.sense_ = highspy.ObjSense.kMaximize
    # column-wise matrix
    ra = np.asarray(rows, dtype=np.int64)
    ca = np.asarray(cols, dtype=np.int64)
    va = np.asarray(vals, dtype=float)
    order = np.lexsort((ra, ca))  # by column, then row
    counts = np.bincount(ca, minlength=n) if ca.size else np.zeros(n, dtype=np.int64)
    start = np.concatenate(([0], np.cumsum(counts))).astype(np.int32)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = start
    lp.a_matrix_.index_ = ra[order].astype(np.int32)
    lp.a_matrix_.value_ = va[order]
    is_mip = any(t in "BINS" for t in integ)
    if is_mip:
        vt = highspy.HighsVarType
        mapping = {"B": vt.kInteger, "I": vt.kInteger, "C": vt.kContinuous,
                   "S": getattr(vt, "kSemiContinuous", vt.kContinuous),
                   "N": getattr(vt, "kSemiInteger", vt.kInteger)}
        lp.integrality_ = [mapping.get(t, vt.kContinuous) for t in integ]
    st = h.passModel(lp)
    note = None
    if is_mip and starts and all(s is not None for s in starts) and n > 0:
        try:
            sol0 = highspy.HighsSolution()
            sol0.col_value = [float(s) for s in starts]
            h.setSolution(sol0)
            note = "mip_start"
        except Exception as e:  # noqa: BLE001
            note = "mip_start_failed: %r" % (e,)
    h.run()
    ms = h.getModelStatus()
    info = h.getInfo()
    MS = highspy.HighsModelStatus
    table = {
        "kOptimal": GRB.OPTIMAL, "kInfeasible": GRB.INFEASIBLE, "kUnboundedOrInfeasible": GRB.INF_OR_UNBD,
        "kUnbounded": GRB.UNBOUNDED, "kTimeLimit": GRB.TIME_LIMIT, "kIterationLimit": GRB.ITERATION_LIMIT,
        "kSolutionLimit": GRB.SOLUTION_LIMIT, "kInterrupt": GRB.INTERRUPTED, "kObjectiveBound": GRB.CUTOFF,
        "kObjectiveTarget": GRB.USER_OBJ_LIMIT, "kModelEmpty": GRB.OPTIMAL, "kMemoryLimit": GRB.MEM_LIMIT,
    }
    name, status = str(ms).split(".")[-1], GRB.NUMERIC
    for nm, gs in table.items():
        member = getattr(MS, nm, None)
        if member is not None and ms == member:
            name, status = nm, gs
            break
    out = {"status": status, "backend": "highspy", "note": note, "highs_status": name}
    feasible = False
    try:
        feasible = int(info.primal_solution_status) == 2
    except Exception:  # noqa: BLE001
        feasible = status == GRB.OPTIMAL
    if n == 0 and name == "kModelEmpty":
        feasible = True
    if feasible:
        sol = h.getSolution()
        out["x"] = list(sol.col_value) if n else []
        out["row_value"] = list(sol.row_value) if m else []
        out["obj"] = float(info.objective_function_value) if n else float(objcon)
        if not is_mip and sol.dual_valid:
            out["row_dual"] = list(sol.row_dual)
            out["col_dual"] = list(sol.col_dual)
    try:
        if is_mip:
            out["bound"] = float(info.mip_dual_bound)
            out["gap"] = float(info.mip_gap)
            out["nodes"] = int(info.mip_node_count)
        elif feasible:
            out["bound"] = out["obj"]
            out["gap"] = 0.0
        out["iters"] = int(info.simplex_iteration_count)
    except Exception:  # noqa: BLE001
        pass
    del MS, st
    return out


def _solve_scipy(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, sense, objcon, limit, gap):
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csr_matrix
    c = np.array(cost, dtype=float) * (-1.0 if sense == GRB.MAXIMIZE else 1.0)
    integrality = np.array([1 if t in "BIN" else 0 for t in integ])
    cons = []
    if m:
        A = csr_matrix((vals, (rows, cols)), shape=(m, n))
        cons.append(LinearConstraint(A, np.array(rlo), np.array(rhi)))
    r = milp(c, integrality=integrality, bounds=Bounds(np.array(lb), np.array(ub)), constraints=cons,
             options={"time_limit": float(limit), "mip_rel_gap": float(gap), "disp": False})
    status = {0: GRB.OPTIMAL, 1: GRB.TIME_LIMIT, 2: GRB.INFEASIBLE, 3: GRB.UNBOUNDED}.get(r.status, GRB.NUMERIC)
    out = {"status": status, "backend": "scipy"}
    if r.x is not None:
        out["x"] = list(r.x)
        val = float(np.dot(np.array(cost), r.x)) + objcon
        out["obj"] = val
        if m:
            out["row_value"] = list(csr_matrix((vals, (rows, cols)), shape=(m, n)).dot(r.x))
    return out


__all__ = ["GRB", "Model", "Var", "LinExpr", "QuadExpr", "TempConstr", "Constr", "Column", "Env", "GurobiError",
           "quicksum", "tupledict", "tuplelist", "multidict", "max_", "min_", "abs_", "and_", "or_", "norm",
           "setParam", "disposeDefaultEnv", "set_deadline"]
