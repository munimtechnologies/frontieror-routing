"""gpshim: a small gurobipy-compatible modelling layer that solves with the open-source HiGHS solver.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization. Contains no Gurobi software: it re-implements the common
part of the gurobipy modelling API (Model, addVar/addVars, addConstr, quicksum, LinExpr, QuadExpr, tupledict, GRB
constants, X/ObjVal/Status/...) in pure Python and hands the model to HiGHS through highspy, or to
scipy.optimize.milp (also HiGHS) when highspy is missing.

Use: put `sys.modules["gurobipy"] = gpshim` before running a script written for gurobipy, or `import gpshim as gp`.

Supported (0.2.0):
- continuous, binary, integer (and semi-continuous via HiGHS) variables; linear constraints (<=, >=, ==, ranges);
  linear objectives with a constant; maximise/minimise; MIP starts (Var.Start); LP duals (Pi, RC) for pure LPs;
  TimeLimit, MIPGap, Seed.
- indicator constraints (big-M from finite variable bounds).
- lazy-constraint callbacks (model.optimize(cb) with cbLazy at MIPSOL): emulated by row generation. The MIP is solved,
  the callback sees the integer solution (where == GRB.Callback.MIPSOL, cbGetSolution, cbGet), every constraint it
  passes to cbLazy is added, and the MIP is solved again until the callback adds no violated constraint. A solution is
  reported only when it satisfies every lazy constraint, as in Gurobi. cbCut is accepted and treated like cbLazy;
  MIPNODE callbacks are never called (user cuts are optional).
- quadratic terms, reformulated exactly when possible: a product with a binary variable (x*b, b*b, b^2) becomes a
  linear McCormick system, which is exact when the other factor has finite bounds; a product with a fixed variable
  becomes linear. A pure continuous model with a quadratic objective goes to HiGHS's QP solver (convex only).
  Otherwise a convex square (a*x^2 with a > 0 on a minimised objective or on the <= side of a constraint, x with
  finite bounds) is replaced by the piecewise-linear interpolation of x^2 on MV2_GPSHIM_PWL_SEGMENTS (default 32)
  equal segments. That over-estimates x^2, so every reported solution is feasible for the original quadratic
  constraint, and the objective is approximate (error at most (U-L)^2/(4K^2) per square).
- general constraints max, min, abs, and, or, PWL (exact, with binaries; needs finite bounds) and multiple
  objectives (setObjectiveN: hierarchical by priority, blended by weight within a priority).
Not supported (raise GurobiError, so a caller can fall back): products of two non-binary variables that are not a
convex square as above, quadratic objectives in MIPs that are not convex squares, the matrix API (addMVar), SOS,
setPWLObj, solution pools (Xn), IIS (computeIIS does nothing and marks no constraint as part of an IIS).

A global deadline (set_deadline(epoch_seconds) or the MV2_GPSHIM_DEADLINE environment variable) caps every
optimize() call, whatever TimeLimit the script asks for. If MV2_GPSHIM_LOG names a file, each optimize() appends one
JSON line with the model size, sense, status, objective and the reformulations used.
"""
import itertools
import json
import numbers
import os
import time

__version__ = "0.2.0"
INF = float("inf")
_DEADLINE = [None]
_STATS = []
_SEQ = itertools.count()


def set_deadline(epoch_seconds):
    _DEADLINE[0] = None if epoch_seconds is None else float(epoch_seconds)


if os.environ.get("MV2_GPSHIM_DEADLINE"):
    try:
        set_deadline(float(os.environ["MV2_GPSHIM_DEADLINE"]))
    except ValueError:
        pass


def _pwl_segments():
    try:
        return max(2, int(os.environ.get("MV2_GPSHIM_PWL_SEGMENTS", "32")))
    except ValueError:
        return 32


class GurobiError(Exception):
    def __init__(self, *args):
        super().__init__(*args)
        self.errno = 10001
        self.message = str(args[0]) if args else ""


class _AttrError(GurobiError, AttributeError):
    """Raised when an attribute has no value yet; hasattr() then returns False, as scripts expect."""


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
        MIP_OBJBST = 3000
        MIP_OBJBND = 3001
        MIP_NODCNT = 3002
        MIP_SOLCNT = 3003
        MIPSOL_SOL = 4001
        MIPSOL_OBJ = 4002
        MIPSOL_OBJBST = 4003
        MIPSOL_OBJBND = 4004
        MIPSOL_NODCNT = 4005
        MIPSOL_SOLCNT = 4006
        MIPNODE_STATUS = 5001
        MSG_STRING = 6001
        RUNTIME = 6002

    callback = Callback


def _num(o):
    return isinstance(o, numbers.Number) and not isinstance(o, complex)


def _big(v):
    return v is None or v >= 1e30


def _bounds(v):
    lo, hi = v._lb, v._ub
    if v._vt == "B":
        lo, hi = max(lo, 0.0), min(hi, 1.0)
    return lo, hi


def _isbin(v):
    lo, hi = _bounds(v)
    return (v._vt == "B" or v._vt == "I") and lo >= 0.0 and hi <= 1.0


def _finite(*xs):
    return all(-1e30 < x < 1e30 for x in xs)


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
        return _lin(self)._iadd(o, 1.0)

    def __radd__(self, o):
        return _lin(self)._iadd(o, 1.0)

    def __sub__(self, o):
        return _lin(self)._iadd(o, -1.0)

    def __rsub__(self, o):
        return _lin(self)._scale(-1.0)._iadd(o, 1.0)

    def __neg__(self):
        return _lin(self)._scale(-1.0)

    def __pos__(self):
        return _lin(self)

    def __mul__(self, o):
        if _num(o):
            return _lin(self)._scale(float(o))
        if isinstance(o, QuadExpr):
            return o.__mul__(self)
        if isinstance(o, _Expr):
            return _product(self, o)
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, o):
        if _num(o):
            return _lin(self)._scale(1.0 / float(o))
        if isinstance(o, LinExpr) and not o.t:
            return _lin(self)._scale(1.0 / o.c)
        raise GurobiError("gpshim: division by an expression is not supported")

    def __pow__(self, k):
        if k == 1:
            return _lin(self)
        if k == 0:
            return LinExpr(1.0)
        if k == 2:
            return _product(self, self)
        raise GurobiError("gpshim: powers above 2 are not supported")


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
        object.__setattr__(self, "_seq", next(_SEQ))

    def __repr__(self):
        return "<gpshim.Var %s>" % (self._name or "C%d" % self._idx)

    def __getattr__(self, name):
        k = name.lower()
        if k == "x":
            if self._x is None:
                raise _AttrError("Unable to retrieve attribute 'X'")
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
                raise _AttrError("Unable to retrieve attribute 'RC'")
            return self._rc
        if k == "index":
            return self._idx
        if k in ("varhintval", "varhintpri", "branchpriority", "partition", "poolignore", "iislb", "iisub"):
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
        """Add s*o in place and return the result (a new QuadExpr when o is quadratic)."""
        if isinstance(o, Var):
            self.t[o] = self.t.get(o, 0.0) + s
        elif isinstance(o, QuadExpr):
            return QuadExpr(self)._iadd(o, s)
        elif isinstance(o, LinExpr):
            t = self.t
            for v, a in o.t.items():
                t[v] = t.get(v, 0.0) + s * a
            self.c += s * o.c
        elif _num(o):
            self.c += s * float(o)
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
        if isinstance(expr, QuadExpr):
            raise GurobiError("gpshim: LinExpr.add() of a quadratic expression; use a QuadExpr")
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


def _lin(o):
    if isinstance(o, LinExpr):
        return LinExpr(o)
    if isinstance(o, Var):
        return LinExpr(o)
    if _num(o):
        return LinExpr(float(o))
    raise GurobiError("gpshim: expected a linear expression, got %r" % (type(o),))


def _copy_expr(o):
    return QuadExpr(o) if isinstance(o, QuadExpr) else _lin(o)


def _product(a, b):
    A, B = _lin(a), _lin(b)
    if not A.t:
        return B._scale(A.c)
    if not B.t:
        return A._scale(B.c)
    q = QuadExpr()
    lin = q.lin
    lin.c = A.c * B.c
    if B.c:
        for v, x in A.t.items():
            lin.t[v] = lin.t.get(v, 0.0) + x * B.c
    if A.c:
        for v, x in B.t.items():
            lin.t[v] = lin.t.get(v, 0.0) + x * A.c
    for v, x in A.t.items():
        for w, y in B.t.items():
            q._addq(v, w, x * y)
    return q


class QuadExpr(_Expr):
    """lin (a LinExpr) + sum of coefficient * v * w over the pairs in q (keys ordered by creation)."""

    def __init__(self, expr=None):
        self.lin = LinExpr()
        self.q = {}
        if expr is None:
            return
        if isinstance(expr, QuadExpr):
            self.lin = LinExpr(expr.lin)
            self.q = dict(expr.q)
        else:
            self.lin = _lin(expr)

    def __repr__(self):
        return "<gpshim.QuadExpr %d quadratic + %d linear terms + %g>" % (len(self.q), len(self.lin.t), self.lin.c)

    def _addq(self, v, w, a):
        if v._seq > w._seq:
            v, w = w, v
        k = (v, w)
        self.q[k] = self.q.get(k, 0.0) + a

    def _scale(self, s):
        self.lin._scale(s)
        if s != 1.0:
            for k in self.q:
                self.q[k] *= s
        return self

    def _iadd(self, o, s):
        if isinstance(o, QuadExpr):
            self.lin._iadd(o.lin, s)
            for (v, w), a in o.q.items():
                self._addq(v, w, s * a)
            return self
        r = self.lin._iadd(o, s)
        if r is NotImplemented:
            return NotImplemented
        return self

    def __add__(self, o):
        return QuadExpr(self)._iadd(o, 1.0)

    __radd__ = __add__

    def __sub__(self, o):
        return QuadExpr(self)._iadd(o, -1.0)

    def __rsub__(self, o):
        return QuadExpr(self)._scale(-1.0)._iadd(o, 1.0)

    def __neg__(self):
        return QuadExpr(self)._scale(-1.0)

    def __pos__(self):
        return QuadExpr(self)

    def __mul__(self, o):
        if _num(o):
            return QuadExpr(self)._scale(float(o))
        if isinstance(o, LinExpr) and not o.t:
            return QuadExpr(self)._scale(o.c)
        if isinstance(o, QuadExpr) and not o.q and not o.lin.t:
            return QuadExpr(self)._scale(o.lin.c)
        if isinstance(o, _Expr) and not self.q:
            if isinstance(o, QuadExpr):
                return o.__mul__(self.lin)
            return _product(self.lin, o)
        if isinstance(o, _Expr):
            raise GurobiError("gpshim: expressions above degree 2 are not supported")
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, o):
        if _num(o):
            return QuadExpr(self)._scale(1.0 / float(o))
        raise GurobiError("gpshim: division by an expression is not supported")

    def __pow__(self, k):
        if k == 1:
            return QuadExpr(self)
        if k == 2 and not self.q:
            return _product(self.lin, self.lin)
        raise GurobiError("gpshim: expressions above degree 2 are not supported")

    def __iadd__(self, o):
        return self._iadd(o, 1.0)

    def __isub__(self, o):
        return self._iadd(o, -1.0)

    def __imul__(self, o):
        return self * o

    def add(self, expr, mult=1.0):
        if self._iadd(expr, float(mult)) is NotImplemented:
            raise GurobiError("gpshim: cannot add %r to a QuadExpr" % (type(expr),))

    def addTerms(self, coeffs, vars_, vars2=None):
        if vars2 is None:
            self.lin.addTerms(coeffs, vars_)
            return
        if isinstance(vars_, Var):
            self._addq(vars_, vars2, float(coeffs))
            return
        for a, v, w in zip(coeffs, vars_, vars2):
            self._addq(v, w, float(a))

    def addConstant(self, c):
        self.lin.c += float(c)

    def getConstant(self):
        return self.lin.c

    def getLinExpr(self):
        return LinExpr(self.lin)

    def size(self):
        return len(self.q)

    def getVar1(self, i):
        return list(self.q)[i][0]

    def getVar2(self, i):
        return list(self.q)[i][1]

    def getCoeff(self, i):
        return list(self.q.values())[i]

    def clear(self):
        self.lin = LinExpr()
        self.q = {}

    def copy(self):
        return QuadExpr(self)

    def getValue(self):
        return self.lin.getValue() + sum(a * v.X * w.X for (v, w), a in self.q.items())


class TempConstr:
    __array_ufunc__ = None

    def __init__(self, lhs, sense, rhs):
        e = _copy_expr(lhs) if isinstance(lhs, _Expr) else LinExpr(float(lhs))
        if isinstance(rhs, (list, tuple)) and len(rhs) == 2 and sense == GRB.EQUAL:  # expr == [lb, ub]
            if isinstance(e, QuadExpr):
                raise GurobiError("gpshim: quadratic range constraints are not supported")
            self.expr, self.sense, self.lo, self.hi = e, "R", float(rhs[0]), float(rhs[1])
            return
        if isinstance(rhs, _Expr):
            e = e._iadd(rhs, -1.0)
        elif _num(rhs):
            e = e._iadd(float(rhs), -1.0)
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


def _row_of(tc):
    """(terms, lo, hi) of a linear TempConstr."""
    e = tc.expr
    if isinstance(e, QuadExpr):
        if e.q:
            raise GurobiError("gpshim: quadratic lazy constraints are not supported")
        e = e.lin
    if tc.sense == "R":
        return dict(e.t), tc.lo - e.c, tc.hi - e.c
    r = -e.c
    if tc.sense == GRB.LESS_EQUAL:
        return dict(e.t), -INF, r
    if tc.sense == GRB.GREATER_EQUAL:
        return dict(e.t), r, INF
    return dict(e.t), r, r


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
                raise _AttrError("Unable to retrieve attribute 'Pi'")
            return self._pi
        if k == "slack":
            if self._slack is None:
                raise _AttrError("Unable to retrieve attribute 'Slack'")
            return self._slack
        if k == "rhs":
            return self._rhs
        if k == "sense":
            return self._sense
        if k == "constrname":
            return self._name
        if k == "index":
            return self._idx
        if k in ("lazy", "iisconstr"):
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


class QConstr:
    """A quadratic constraint lin + sum q <sense> rhs; reformulated at optimize() time."""

    def __init__(self, model, expr, sense, name):
        self._m = model
        self._t = dict(expr.lin.t)
        self._q = dict(expr.q)
        self._sense = sense
        self._rhs = -expr.lin.c
        self._name = name or ""
        self._removed = False

    def __repr__(self):
        return "<gpshim.QConstr %s>" % self._name

    def __getattr__(self, name):
        k = name.lower()
        if k == "qcname":
            return self._name
        if k == "qcsense":
            return self._sense
        if k == "qcrhs":
            return self._rhs
        if k == "iisqconstr":
            return 0
        raise AttributeError(name)

    def getAttr(self, name):
        return getattr(self, name)


class GenConstr:
    def __init__(self, spec):
        self._spec = spec
        self._removed = False

    def __getattr__(self, name):
        if name.lower() == "genconstrname":
            return self._spec.get("name", "")
        if name.lower() == "genconstrtype":
            return self._spec["kind"]
        raise AttributeError(name)


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
            e = e._iadd(v, 1.0)
        return e

    def prod(self, coeff, *pattern):
        e = LinExpr()
        for k, v in self.items():
            if pattern and not _match(k, pattern):
                continue
            if k in coeff:
                e = e._iadd(v * coeff[k], 1.0)
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
        r = e._iadd(it, 1.0)
        if r is NotImplemented:
            raise GurobiError("gpshim: cannot add %r to an expression" % (type(it),))
        e = r
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


def _implied_bounds(rows, passes=3):
    """Bounds implied by the linear rows (terms, lo, hi) and the declared bounds: standard activity-based bound
    propagation. Every bound returned holds for every feasible point, so big-M and McCormick terms built from it are
    still exact."""
    L, U = {}, {}
    for terms, _, _ in rows:
        for v in terms:
            if v not in L:
                L[v], U[v] = _bounds(v)
    for _ in range(passes):
        changed = False
        for terms, lo, hi in rows:
            if len(terms) > 5000:
                continue
            mn = mx = 0.0
            nmn = nmx = 0
            for v, a in terms.items():
                if a > 0:
                    if L[v] == -INF:
                        nmn += 1
                    else:
                        mn += a * L[v]
                    if U[v] == INF:
                        nmx += 1
                    else:
                        mx += a * U[v]
                elif a < 0:
                    if U[v] == INF:
                        nmn += 1
                    else:
                        mn += a * U[v]
                    if L[v] == -INF:
                        nmx += 1
                    else:
                        mx += a * L[v]
            for v, a in terms.items():
                if a == 0.0:
                    continue
                if hi < INF:  # a v <= hi - (min activity of the others)
                    own_inf = (a > 0 and L[v] == -INF) or (a < 0 and U[v] == INF)
                    if nmn - (1 if own_inf else 0) == 0:
                        own = 0.0 if own_inf else (a * L[v] if a > 0 else a * U[v])
                        b = (hi - (mn - own)) / a
                        b += (1e-7 * (1.0 + abs(b))) * (1 if a > 0 else -1)
                        if a > 0 and b < U[v] - 1e-9:
                            U[v], changed = b, True
                        elif a < 0 and b > L[v] + 1e-9:
                            L[v], changed = b, True
                if lo > -INF:  # a v >= lo - (max activity of the others)
                    own_inf = (a > 0 and U[v] == INF) or (a < 0 and L[v] == -INF)
                    if nmx - (1 if own_inf else 0) == 0:
                        own = 0.0 if own_inf else (a * U[v] if a > 0 else a * L[v])
                        b = (lo - (mx - own)) / a
                        b -= (1e-7 * (1.0 + abs(b))) * (1 if a > 0 else -1)
                        if a > 0 and b > L[v] + 1e-9:
                            L[v], changed = b, True
                        elif a < 0 and b < U[v] - 1e-9:
                            U[v], changed = b, True
        if not changed:
            break
    return {v: (L[v], U[v]) for v in L}


class _Reform:
    """Auxiliary columns and rows that turn quadratic terms and general constraints into a linear model."""

    def __init__(self, model, segments, base_rows=()):
        self.m = model
        self.K = segments
        self.base = base_rows
        self._imp = None
        self.vars = []
        self.rows = []
        self.prod = {}
        self.sq = {}
        self.n_prod = self.n_sec = self.n_gen = 0
        self.n_implied = 0

    def bnd(self, v):
        """Declared bounds, or bounds implied by the linear constraints when a declared one is infinite."""
        lo, hi = _bounds(v)
        if _finite(lo, hi):
            return lo, hi
        if self._imp is None:
            self._imp = _implied_bounds(self.base)
        b = self._imp.get(v)
        if b is None:
            return lo, hi
        if _finite(*b):
            self.n_implied += 1
        return b

    def newvar(self, lb, ub, vt="C"):
        v = Var(self.m, lb, ub, 0.0, vt, "")
        self.vars.append(v)
        return v

    def exact(self, v, w, a, lin):
        """Add a*v*w to lin (Var -> coefficient) exactly with linear pieces; False if that is impossible."""
        lv, uv = self.bnd(v)
        lw, uw = self.bnd(w)
        if lv == uv:
            lin[w] = lin.get(w, 0.0) + a * lv
            return True
        if lw == uw:
            lin[v] = lin.get(v, 0.0) + a * lw
            return True
        if v is w:
            if _isbin(v):
                lin[v] = lin.get(v, 0.0) + a
                return True
            return False
        if _isbin(v):
            b, y, L, U = v, w, lw, uw
        elif _isbin(w):
            b, y, L, U = w, v, lv, uv
        else:
            return False
        if not _finite(L, U):
            return False
        key = (v, w)
        z = self.prod.get(key)
        if z is None:
            z = self.newvar(min(0.0, L), max(0.0, U))
            self.rows.append(({z: 1.0, b: -U}, -INF, 0.0))  # z <= U b
            self.rows.append(({z: 1.0, b: -L}, 0.0, INF))  # z >= L b
            self.rows.append(({z: 1.0, y: -1.0, b: -L}, -INF, -L))  # z <= y - L (1 - b)
            self.rows.append(({z: 1.0, y: -1.0, b: -U}, -U, INF))  # z >= y - U (1 - b)
            self.prod[key] = z
            self.n_prod += 1
        lin[z] = lin.get(z, 0.0) + a
        return True

    def secant(self, v, a, lin):
        """Add a*s to lin where s >= the piecewise-linear interpolation of v^2 on K segments of [L, U]."""
        L, U = self.bnd(v)
        if not _finite(L, U):
            return False
        z = self.sq.get(v)
        if z is None:
            lo = 0.0 if L <= 0.0 <= U else min(L * L, U * U)
            z = self.newvar(lo, max(L * L, U * U))
            K = self.K
            for k in range(K):
                p = L + (U - L) * k / K
                q = L + (U - L) * (k + 1) / K
                self.rows.append(({z: 1.0, v: -(p + q)}, -p * q, INF))  # z >= (p+q) v - p q
            self.sq[v] = z
            self.n_sec += 1
        lin[z] = lin.get(z, 0.0) + a
        return True

    def qconstr(self, qc):
        lin = dict(qc._t)
        sign = 1.0 if qc._sense == GRB.LESS_EQUAL else (-1.0 if qc._sense == GRB.GREATER_EQUAL else 0.0)
        for (v, w), a in qc._q.items():
            if a == 0.0:
                continue
            if self.exact(v, w, a, lin):
                continue
            if v is w and sign != 0.0 and a * sign > 0 and self.secant(v, a, lin):
                continue
            raise GurobiError("gpshim: quadratic constraint %r has a term that is neither a product with a binary "
                              "variable nor a bounded convex square" % qc._name)
        r = qc._rhs
        if qc._sense == GRB.LESS_EQUAL:
            self.rows.append((lin, -INF, r))
        elif qc._sense == GRB.GREATER_EQUAL:
            self.rows.append((lin, r, INF))
        else:
            self.rows.append((lin, r, r))

    def gen(self, g):
        kind = g["kind"]
        self.n_gen += 1
        if kind in ("max", "min"):
            r = g["res"]
            items = [(v,) + tuple(self.bnd(v)) for v in g["vars"]]
            if g.get("const") is not None:
                items.append((None, float(g["const"]), float(g["const"])))
            if not items:
                raise GurobiError("gpshim: %s constraint without arguments" % kind)
            if not all(_finite(L, U) for _, L, U in items):
                raise GurobiError("gpshim: %s constraint needs finite bounds on its arguments" % kind)
            zs = [self.newvar(0.0, 1.0, "B") for _ in items]
            self.rows.append(({z: 1.0 for z in zs}, 1.0, 1.0))
            if kind == "max":
                Ur = max(U for _, _, U in items)
                for (v, L, U), z in zip(items, zs):
                    if v is None:
                        self.rows.append(({r: 1.0}, L, INF))
                        self.rows.append(({r: 1.0, z: Ur - L}, -INF, Ur))
                    else:
                        self.rows.append(({r: 1.0, v: -1.0}, 0.0, INF))
                        self.rows.append(({r: 1.0, v: -1.0, z: Ur - L}, -INF, Ur - L))
            else:
                Lr = min(L for _, L, _ in items)
                for (v, L, U), z in zip(items, zs):
                    if v is None:
                        self.rows.append(({r: 1.0}, -INF, U))
                        self.rows.append(({r: 1.0, z: -(U - Lr)}, Lr, INF))
                    else:
                        self.rows.append(({r: 1.0, v: -1.0}, -INF, 0.0))
                        self.rows.append(({r: 1.0, v: -1.0, z: -(U - Lr)}, -(U - Lr), INF))
        elif kind == "abs":
            r, x = g["res"], g["arg"]
            L, U = self.bnd(x)
            if not _finite(L, U):
                raise GurobiError("gpshim: abs constraint needs finite bounds on its argument")
            M = max(abs(L), abs(U))
            z = self.newvar(0.0, 1.0, "B")
            self.rows.append(({r: 1.0, x: -1.0}, 0.0, INF))
            self.rows.append(({r: 1.0, x: 1.0}, 0.0, INF))
            self.rows.append(({r: 1.0, x: -1.0, z: 2.0 * M}, -INF, 2.0 * M))
            self.rows.append(({r: 1.0, x: 1.0, z: -2.0 * M}, -INF, 0.0))
        elif kind == "and":
            r, bs = g["res"], list(g["vars"])
            for b in bs:
                self.rows.append(({r: 1.0, b: -1.0}, -INF, 0.0))
            t = {r: 1.0}
            for b in bs:
                t[b] = t.get(b, 0.0) - 1.0
            self.rows.append((t, -(len(bs) - 1.0), INF))
        elif kind == "or":
            r, bs = g["res"], list(g["vars"])
            for b in bs:
                self.rows.append(({r: 1.0, b: -1.0}, 0.0, INF))
            t = {r: 1.0}
            for b in bs:
                t[b] = t.get(b, 0.0) - 1.0
            self.rows.append((t, -INF, 0.0))
        elif kind == "pwl":
            x, y = g["x"], g["y"]
            xp, yp = [float(a) for a in g["xpts"]], [float(a) for a in g["ypts"]]
            n = len(xp)
            if n == 0 or n != len(yp):
                raise GurobiError("gpshim: bad PWL points")
            if n == 1:
                self.rows.append(({x: 1.0}, xp[0], xp[0]))
                self.rows.append(({y: 1.0}, yp[0], yp[0]))
                return
            lam = [self.newvar(0.0, 1.0) for _ in range(n)]
            zs = [self.newvar(0.0, 1.0, "B") for _ in range(n - 1)]
            self.rows.append(({z: 1.0 for z in zs}, 1.0, 1.0))
            self.rows.append(({l_: 1.0 for l_ in lam}, 1.0, 1.0))
            tx, ty = {x: 1.0}, {y: 1.0}
            for l_, a, b in zip(lam, xp, yp):
                tx[l_] = -a
                ty[l_] = -b
            self.rows.append((tx, 0.0, 0.0))
            self.rows.append((ty, 0.0, 0.0))
            for k in range(n):
                t = {lam[k]: 1.0}
                if k > 0:
                    t[zs[k - 1]] = -1.0
                if k < n - 1:
                    t[zs[k]] = t.get(zs[k], 0.0) - 1.0
                self.rows.append((t, -INF, 0.0))
        else:
            raise GurobiError("gpshim: general constraint %r is not supported" % kind)


class Model:
    def __init__(self, name="", env=None):
        # internal names start with _gp so that user attributes such as model._vars (callback data) never clash
        object.__setattr__(self, "_gpv", [])
        object.__setattr__(self, "_gpc", [])
        object.__setattr__(self, "_gpi", [])
        object.__setattr__(self, "_gpq", {})
        object.__setattr__(self, "_gpqc", [])
        object.__setattr__(self, "_gpg", [])
        object.__setattr__(self, "_gpobjn", {})
        object.__setattr__(self, "_gpcbs", None)
        object.__setattr__(self, "_gpterm", False)
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
                raise _AttrError("Unable to retrieve attribute 'ObjVal'")
            return res["ObjVal"]
        if k in ("objbound", "objboundc"):
            if res["ObjBound"] is None:
                raise _AttrError("Unable to retrieve attribute 'ObjBound'")
            return res["ObjBound"]
        if k == "mipgap":
            if res["MIPGap"] is None:
                raise _AttrError("Unable to retrieve attribute 'MIPGap'")
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
            return int(any(v._vt in "BIN" for v in self._live_vars()) or bool(self._gpi) or bool(self._gpg))
        if k == "isqp":
            return int(bool(self._gpq))
        if k == "isqcp":
            return int(bool(self._live_qcons()))
        if k == "modelsense":
            return self._gps
        if k == "objcon":
            return self._gpo
        if k == "numnzs":
            return sum(len(c._t) for c in self._live_cons())
        if k == "numqconstrs":
            return len(self._live_qcons())
        if k == "numqnzs":
            return sum(len(c._q) for c in self._live_qcons())
        if k == "numgenconstrs":
            return len(self._gpi) + len(self._gpg)
        if k == "numsos":
            return 0
        if k == "numobj":
            return max(1, len(self._gpobjn))
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
        if isinstance(tc.expr, QuadExpr):
            if tc.expr.q:
                qc = QConstr(self, tc.expr, tc.sense, name)
                self._gpqc.append(qc)
                return qc
            tc.expr = tc.expr.lin
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
    addQConstr = addConstr

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
        if not isinstance(tc, TempConstr) or tc.sense == "R" or isinstance(tc.expr, QuadExpr):
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

    def _add_gen(self, spec):
        g = GenConstr(spec)
        self._gpg.append(g)
        return g

    def addGenConstrMax(self, resvar, vars, constant=None, name=""):  # noqa: A002 - gurobipy's name
        return self._add_gen({"kind": "max", "res": resvar, "vars": list(vars), "const": constant, "name": name})

    def addGenConstrMin(self, resvar, vars, constant=None, name=""):  # noqa: A002
        return self._add_gen({"kind": "min", "res": resvar, "vars": list(vars), "const": constant, "name": name})

    def addGenConstrAbs(self, resvar, argvar, name=""):
        return self._add_gen({"kind": "abs", "res": resvar, "arg": argvar, "name": name})

    def addGenConstrAnd(self, resvar, vars, name=""):  # noqa: A002
        return self._add_gen({"kind": "and", "res": resvar, "vars": list(vars), "name": name})

    def addGenConstrOr(self, resvar, vars, name=""):  # noqa: A002
        return self._add_gen({"kind": "or", "res": resvar, "vars": list(vars), "name": name})

    def addGenConstrPWL(self, xvar, yvar, xpts, ypts, name="", options=""):
        return self._add_gen({"kind": "pwl", "x": xvar, "y": yvar, "xpts": list(xpts), "ypts": list(ypts),
                              "name": name})

    def addMVar(self, *a, **k):
        raise GurobiError("gpshim: the matrix API (addMVar) is not supported")

    addMConstr = addMVar
    addSOS = _unsupported("addSOS")
    setPWLObj = _unsupported("setPWLObj")
    addGenConstrPow = _unsupported("addGenConstrPow")
    addGenConstrExp = _unsupported("addGenConstrExp")
    addGenConstrLog = _unsupported("addGenConstrLog")
    addGenConstrNL = _unsupported("addGenConstrNL")

    def computeIIS(self):
        """No IIS is computed; every IISConstr attribute reads 0."""
        object.__setattr__(self, "_gpiis", "not computed")

    # ---------------------------------------------------------------- callbacks (row generation)
    def _cb(self):
        cb = self._gpcbs
        if cb is None:
            raise GurobiError("gpshim: callback method called outside a callback")
        return cb

    def cbGetSolution(self, vars):  # noqa: A002
        x = self._cb()["x"]
        if isinstance(vars, Var):
            return x.get(vars, 0.0)
        if isinstance(vars, dict):
            return tupledict((k, x.get(v, 0.0)) for k, v in vars.items())
        return [x.get(v, 0.0) for v in vars]

    def cbGet(self, what):
        cb = self._cb()
        C = GRB.Callback
        if what in (C.MIPSOL_OBJ, C.MIPSOL_OBJBST, C.MIP_OBJBST):
            return cb["obj"]
        if what in (C.MIPSOL_OBJBND, C.MIP_OBJBND):
            return cb["bound"]
        if what == C.RUNTIME:
            return time.time() - cb["t0"]
        if what in (C.MIPSOL_SOLCNT, C.MIPSOL_NODCNT, C.MIP_SOLCNT, C.MIP_NODCNT):
            return cb["round"]
        return 0

    def cbLazy(self, lhs, sense=None, rhs=None):
        tc = lhs if sense is None else TempConstr(lhs, _sense_of(sense), rhs)
        self._cb()["pending"].append(_row_of(tc))

    cbCut = cbLazy

    def cbGetNodeRel(self, vars):  # noqa: A002
        raise GurobiError("gpshim: cbGetNodeRel is only available at MIPNODE, which gpshim never calls")

    def cbSetSolution(self, vars, values):  # noqa: A002
        pass

    def cbUseSolution(self):
        return 0

    def cbStopOneMultiObj(self, objnum):
        pass

    # ---------------------------------------------------------------- objective
    def setObjective(self, expr, sense=None):
        if isinstance(expr, QuadExpr):
            q, e = dict(expr.q), expr.lin
        else:
            q, e = {}, (LinExpr(expr) if isinstance(expr, _Expr) else LinExpr(float(expr)))
        for v in self._gpv:
            object.__setattr__(v, "_obj", 0.0)
        for v, a in e.t.items():
            object.__setattr__(v, "_obj", v._obj + a)
        object.__setattr__(self, "_gpo", e.c)
        object.__setattr__(self, "_gpq", q)
        if sense is not None:
            object.__setattr__(self, "_gps", int(sense))

    def setObjectiveN(self, expr, index, priority=0, weight=1.0, abstol=1e-6, reltol=0.0, name=""):
        if isinstance(expr, QuadExpr):
            if expr.q:
                raise GurobiError("gpshim: quadratic objectives in setObjectiveN are not supported")
            expr = expr.lin
        e = LinExpr(expr) if isinstance(expr, _Expr) else LinExpr(float(expr))
        self._gpobjn[int(index)] = {"expr": e, "priority": int(priority), "weight": float(weight),
                                    "abstol": float(abstol), "reltol": float(reltol), "name": name}

    def getObjective(self, index=None):
        if index is not None and self._gpobjn:
            return LinExpr(self._gpobjn[int(index)]["expr"])
        e = LinExpr(self._gpo)
        for v in self._gpv:
            if v._obj and not v._removed:
                e.t[v] = v._obj
        if self._gpq:
            q = QuadExpr(e)
            q.q = dict(self._gpq)
            return q
        return e

    def getVars(self):
        return self._live_vars()

    def getConstrs(self):
        return self._live_cons()

    def getQConstrs(self):
        return self._live_qcons()

    def getGenConstrs(self):
        return list(self._gpg)

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
        if isinstance(items, (Var, Constr, QConstr)):
            items = [items]
        elif isinstance(items, GenConstr):
            items = [items]
        elif isinstance(items, dict):
            items = list(items.values())
        for it in items:
            if isinstance(it, (Var, Constr, QConstr)):
                object.__setattr__(it, "_removed", True)
            elif isinstance(it, GenConstr) and it in self._gpg:
                self._gpg.remove(it)

    def _live_vars(self):
        return [v for v in self._gpv if not v._removed]

    def _live_cons(self):
        return [c for c in self._gpc if not c._removed]

    def _live_qcons(self):
        return [c for c in self._gpqc if not c._removed]

    def update(self):
        pass

    def reset(self, clearall=0):
        self._gpr.update(Status=GRB.LOADED, SolCount=0, ObjVal=None, ObjBound=None, MIPGap=None)

    def dispose(self):
        pass

    def terminate(self):
        object.__setattr__(self, "_gpterm", True)

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
        object.__setattr__(r, "_gpq", {(vmap[v], vmap[w]): a for (v, w), a in self._gpq.items()
                                       if v in vmap and w in vmap})
        for qc in self._live_qcons():
            nq = QConstr(r, QuadExpr(), qc._sense, qc._name)
            nq._t = {vmap[v]: a for v, a in qc._t.items() if v in vmap}
            nq._q = {(vmap[v], vmap[w]): a for (v, w), a in qc._q.items() if v in vmap and w in vmap}
            nq._rhs = qc._rhs
            r._gpqc.append(nq)

        def mv(o):
            if isinstance(o, Var):
                return vmap.get(o, o)
            if isinstance(o, list):
                return [mv(x) for x in o]
            return o
        for g in self._gpg:
            r._gpg.append(GenConstr({k: mv(val) for k, val in g._spec.items()}))
        for k, s in self._gpobjn.items():
            e = LinExpr()
            e.t = {vmap[v]: a for v, a in s["expr"].t.items() if v in vmap}
            e.c = s["expr"].c
            r._gpobjn[k] = dict(s, expr=e)
        object.__setattr__(r, "_gpo", self._gpo)
        object.__setattr__(r, "_gps", self._gps)
        return r, vmap

    # ---------------------------------------------------------------- solving
    def optimize(self, callback=None):
        t0 = time.time()
        object.__setattr__(self, "_gpterm", False)
        limit = self.Params._get("timelimit", INF)
        limit = INF if limit is None else float(limit)
        if _DEADLINE[0] is not None:
            limit = min(limit, _DEADLINE[0] - time.time())
        limit = max(0.5, limit)
        stop_at = t0 + limit
        V = self._live_vars()
        C = self._live_cons()
        for v in V:
            object.__setattr__(v, "_x", None)
            object.__setattr__(v, "_rc", None)
        brows = []
        for c in C:
            c._idx = len(brows)
            c._pi = None
            c._slack = None
            if c._sense == GRB.LESS_EQUAL:
                brows.append((c._t, -INF, c._rhs))
            elif c._sense == GRB.GREATER_EQUAL:
                brows.append((c._t, c._rhs, INF))
            elif c._sense == GRB.EQUAL:
                brows.append((c._t, c._rhs, c._rhs))
            else:
                brows.append((c._t, c._lo if c._lo is not None else -INF, c._hi if c._hi is not None else INF))
        R = _Reform(self, _pwl_segments(), brows)
        for g in self._gpg:
            R.gen(g._spec)
        for qc in self._live_qcons():
            R.qconstr(qc)
        sense = self._gps
        obj = {v: v._obj for v in V if v._obj}
        rest = {}
        for (v, w), a in self._gpq.items():
            if a == 0.0 or v._removed or w._removed:
                continue
            if not R.exact(v, w, a, obj):
                rest[(v, w)] = a
        is_mip = any(v._vt in "BINS" for v in V) or any(v._vt in "BINS" for v in R.vars)
        try:
            import highspy  # noqa: F401
            have_highspy = True
        except Exception:  # noqa: BLE001
            have_highspy = False
        hess = None
        if rest:
            if not is_mip and have_highspy and not self._gpobjn:
                hess = rest
            else:
                sgn = 1.0 if sense != GRB.MAXIMIZE else -1.0
                for (v, w), a in rest.items():
                    if v is w and a * sgn > 0 and R.secant(v, a, obj):
                        continue
                    raise GurobiError("gpshim: the objective has a quadratic term that is neither a product with a "
                                      "binary variable nor a bounded convex square (or the model is a MIP)")
        cols = V + R.vars
        for i, v in enumerate(cols):
            object.__setattr__(v, "_idx", i)
        n = len(cols)
        lb, ub, integ = [], [], []
        for v in cols:
            lo, hi = _bounds(v)
            lb.append(lo)
            ub.append(hi)
            integ.append(v._vt)
        brows = brows + R.rows
        rlo, rhi, ri, ci, va = [], [], [], [], []
        self._gp_rows(brows, rlo, rhi, ri, ci, va, 0)
        base = {"n": n, "lb": lb, "ub": ub, "integ": integ, "rlo": rlo, "rhi": rhi, "ri": ri, "ci": ci, "va": va,
                "gap": self.Params._get("mipgap", 1e-4), "seed": self.Params._get("seed", None),
                "starts": [v._start for v in V] if not R.vars else None, "highspy": have_highspy}
        hterms = None
        if hess:
            hterms = [(v._idx, w._idx, a) for (v, w), a in hess.items()]
        info = {"products": R.n_prod, "secants": R.n_sec, "gen": R.n_gen, "qp": bool(hterms),
                "implied_bounds_used": R.n_implied}
        if self._gpobjn:
            if callback is not None:
                raise GurobiError("gpshim: callbacks with multiple objectives are not supported")
            res, objval = self._gp_multi(base, cols, stop_at, info)
        else:
            cost = [obj.get(v, 0.0) for v in cols]
            if callback is not None and is_mip:
                res = self._gp_lazy(base, cols, V, cost, self._gpo, sense, hterms, stop_at, callback, t0, info)
            else:
                res = self._gp_core(base, cost, self._gpo, sense, [], hterms, stop_at - time.time())
            objval = res.get("obj")
        x = res.get("x")
        if x is not None:
            for v, xv in zip(V, x):
                xv = float(xv)
                if v._vt in "BI" and abs(xv - round(xv)) < 1e-6:
                    xv = float(round(xv))
                object.__setattr__(v, "_x", xv)
            if res.get("row_value") is not None:
                for c, rv in zip(C, res["row_value"]):
                    if c._sense in (GRB.LESS_EQUAL, GRB.GREATER_EQUAL):
                        c._slack = c._rhs - rv
                    else:
                        c._slack = 0.0 if c._sense == GRB.EQUAL else None
        if not is_mip and not hterms and res.get("row_dual") is not None and x is not None:
            for c, d in zip(C, res["row_dual"]):
                c._pi = float(d)
            for v, d in zip(V, res.get("col_dual") or []):
                object.__setattr__(v, "_rc", float(d))
        rt = time.time() - t0
        self._gpr.update(Status=res["status"], SolCount=1 if x is not None else 0, ObjVal=objval,
                         ObjBound=res.get("bound"), MIPGap=res.get("gap"), Runtime=rt,
                         NodeCount=res.get("nodes", 0), IterCount=res.get("iters", 0))
        _STATS.append({"vars": len(V), "aux_vars": len(R.vars), "constrs": len(C), "nnz": len(va), "mip": is_mip,
                       "sense": "max" if sense == GRB.MAXIMIZE else "min", "status": res["status"],
                       "obj": objval, "bound": res.get("bound"), "time_limit": round(limit, 3),
                       "runtime": round(rt, 3), "backend": res.get("backend"), "note": res.get("note"),
                       "reform": info})
        p = os.environ.get("MV2_GPSHIM_LOG")
        if p:
            try:
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(_STATS[-1], default=str) + "\n")
            except OSError:
                pass

    def _gp_rows(self, rowsdef, rlo, rhi, ri, ci, va, first):
        r = first
        for terms, lo, hi in rowsdef:
            rlo.append(lo)
            rhi.append(hi)
            for v, a in terms.items():
                if a != 0.0 and not v._removed and v._m is self and v._idx >= 0:
                    ri.append(r)
                    ci.append(v._idx)
                    va.append(a)
            r += 1
        return r

    def _gp_core(self, base, cost, objcon, sense, extra, hterms, limit):
        rlo, rhi, ri, ci, va = base["rlo"], base["rhi"], base["ri"], base["ci"], base["va"]
        if extra:
            rlo, rhi, ri, ci, va = list(rlo), list(rhi), list(ri), list(ci), list(va)
            self._gp_rows(extra, rlo, rhi, ri, ci, va, len(base["rlo"]))
        limit = max(0.05, limit)
        if base["highspy"]:
            return _solve_highspy(base["n"], len(rlo), cost, base["lb"], base["ub"], base["integ"], rlo, rhi, ri, ci,
                                  va, sense, objcon, limit, base["gap"], base["seed"], base["starts"], hterms)
        if hterms:
            raise GurobiError("gpshim: quadratic objectives need highspy")
        return _solve_scipy(base["n"], len(rlo), cost, base["lb"], base["ub"], base["integ"], rlo, rhi, ri, ci, va,
                            sense, objcon, limit, base["gap"])

    def _gp_lazy(self, base, cols, V, cost, objcon, sense, hterms, stop_at, callback, t0, info):
        lazy = []
        rounds = 0
        res = {"status": GRB.TIME_LIMIT, "backend": "lazy"}
        while True:
            remaining = stop_at - time.time()
            if remaining < 0.05 and rounds > 0:
                res = {"status": GRB.TIME_LIMIT, "backend": res.get("backend"), "note": "lazy: out of time"}
                break
            res = self._gp_core(base, cost, objcon, sense, lazy, hterms, remaining)
            x = res.get("x")
            if x is None:
                break
            xd = {}
            for v in V:
                xv = float(x[v._idx])
                if v._vt in "BI" and abs(xv - round(xv)) < 1e-6:
                    xv = float(round(xv))
                xd[v] = xv
            cb = {"x": xd, "obj": res.get("obj"), "bound": res.get("bound"), "pending": [], "t0": t0,
                  "round": rounds}
            object.__setattr__(self, "_gpcbs", cb)
            try:
                callback(self, GRB.Callback.MIPSOL)
            finally:
                object.__setattr__(self, "_gpcbs", None)
            rounds += 1
            violated = []
            for terms, lo, hi in cb["pending"]:
                act = sum(a * xd.get(v, 0.0) for v, a in terms.items())
                tol = 1e-5 * max(1.0, abs(lo) if lo > -INF else 0.0, abs(hi) if hi < INF else 0.0)
                if act < lo - tol or act > hi + tol:
                    violated.append((terms, lo, hi))
            if not violated:
                break  # every lazy constraint holds: the solution stands
            if self._gpterm or rounds >= 5000:
                res = {"status": GRB.INTERRUPTED, "backend": res.get("backend"), "note": "lazy: stopped"}
                break
            lazy.extend(cb["pending"])
        info["lazy_rounds"] = rounds
        info["lazy_rows"] = len(lazy)
        return res

    def _gp_multi(self, base, cols, stop_at, info):
        sense = self._gps
        groups = {}
        for idx, s in sorted(self._gpobjn.items()):
            groups.setdefault(s["priority"], []).append(s)
        levels = [groups[p] for p in sorted(groups, reverse=True)]
        extra = []
        best = None
        for k, level in enumerate(levels):
            terms, const = {}, 0.0
            for s in level:
                for v, a in s["expr"].t.items():
                    terms[v] = terms.get(v, 0.0) + s["weight"] * a
                const += s["weight"] * s["expr"].c
            cost = [terms.get(v, 0.0) for v in cols]
            remaining = stop_at - time.time()
            if remaining < 0.05 and best is not None:
                break
            res = self._gp_core(base, cost, const, sense, extra, None, remaining / (len(levels) - k))
            if res.get("x") is None:
                if best is None:
                    best = res
                break
            best = res
            val = float(res["obj"])
            tol = max(max(s["abstol"] for s in level), max(s["reltol"] for s in level) * abs(val),
                      1e-6 * max(1.0, abs(val)))
            if sense == GRB.MAXIMIZE:
                extra.append((terms, val - const - tol, INF))
            else:
                extra.append((terms, -INF, val - const + tol))
        info["levels"] = len(levels)
        x = best.get("x")
        objval = None
        if x is not None:
            first = self._gpobjn[min(self._gpobjn)]["expr"]
            objval = first.c + sum(a * float(x[v._idx]) for v, a in first.t.items() if v._idx >= 0)
        return best, objval


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


def _hessian(highspy, n, hterms, scale):
    """Lower-triangular, column-wise Hessian Q of 0.5 x'Qx for sum a * x_i * x_j (times scale)."""
    import numpy as np
    cols = {}
    for i, j, a in hterms:
        r, c = (i, j) if i >= j else (j, i)
        val = (2.0 * a if i == j else a) * scale
        d = cols.setdefault(c, {})
        d[r] = d.get(r, 0.0) + val
    start, index, value = [0], [], []
    for c in range(n):
        d = cols.get(c, {})
        if d:
            index.append(c)  # diagonal first, as HiGHS expects
            value.append(d.get(c, 0.0))
            for r in sorted(k for k in d if k != c):
                index.append(r)
                value.append(d[r])
        start.append(len(index))
    return (np.array(start, dtype=np.int32), np.array(index, dtype=np.int32), np.array(value, dtype=float))


def _pass_hessian(h, highspy, n, hterms, scale):
    start, index, value = _hessian(highspy, n, hterms, scale)
    try:
        hs = highspy.HighsHessian()
        hs.dim_ = n
        hs.format_ = highspy.HessianFormat.kTriangular
        hs.start_ = start
        hs.index_ = index
        hs.value_ = value
        st = h.passHessian(hs)
    except (AttributeError, TypeError):
        st = h.passHessian(n, len(value), 1, start, index, value)  # 1 = kTriangular
    if str(st).split(".")[-1] == "kError":
        raise GurobiError("gpshim: HiGHS rejected the Hessian")


def _solve_highspy(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, sense, objcon, limit, gap, seed,
                   starts, hterms=None):
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
    flip = bool(hterms) and sense == GRB.MAXIMIZE  # QP: always minimise, flip back afterwards
    lp = highspy.HighsLp()
    lp.num_col_ = n
    lp.num_row_ = m
    c_arr = np.array(cost, dtype=float)
    lp.col_cost_ = -c_arr if flip else c_arr
    lp.col_lower_ = np.array([(-inf if v == -INF else v) for v in lb], dtype=float)
    lp.col_upper_ = np.array([(inf if v == INF else v) for v in ub], dtype=float)
    lp.row_lower_ = np.array([(-inf if v == -INF else v) for v in rlo], dtype=float)
    lp.row_upper_ = np.array([(inf if v == INF else v) for v in rhi], dtype=float)
    lp.offset_ = -float(objcon) if flip else float(objcon)
    if sense == GRB.MAXIMIZE and not flip:
        lp.sense_ = highspy.ObjSense.kMaximize
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
    h.passModel(lp)
    note = None
    if hterms:
        try:
            _pass_hessian(h, highspy, n, hterms, -1.0 if flip else 1.0)
            note = "qp"
        except Exception as e:  # noqa: BLE001
            raise GurobiError("gpshim: HiGHS refused the quadratic objective: %r" % (e,))
    if is_mip and starts and all(s is not None for s in starts) and len(starts) == n and n > 0:
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
    sg = -1.0 if flip else 1.0
    if feasible:
        sol = h.getSolution()
        out["x"] = list(sol.col_value) if n else []
        out["row_value"] = list(sol.row_value) if m else []
        out["obj"] = sg * float(info.objective_function_value) if n else float(objcon)
        if not is_mip and not hterms and sol.dual_valid:
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


__all__ = ["GRB", "Model", "Var", "LinExpr", "QuadExpr", "TempConstr", "Constr", "QConstr", "GenConstr", "Column",
           "Env", "GurobiError", "quicksum", "tupledict", "tuplelist", "multidict", "max_", "min_", "abs_", "and_",
           "or_", "norm", "setParam", "disposeDefaultEnv", "set_deadline"]
