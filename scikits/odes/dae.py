# Authors: B. Malengier based on ode.py
"""
First-order DAE solver

User-friendly interface to various numerical integrators for solving an
algebraic system of first order ODEs with prescribed initial conditions:

         d y(t)
    A * ---------  = f(t,y(t)),
            d t

    y(t=0)[i] = y0[i],
    
      d y(t=0)
    ---------- [i]  = yprime0[i],
        d t

where::

    i = 0, ..., len(y0) - 1
    A is a (possibly singular) matrix of size i x i
    f(t,y) is a vector of size i
    
or more generally, equations of the form 

    G(t,y,y') = 0

class dae
---------

A generic interface class to differential algebraic equations. 
It has the following methods::

    integrator = dae(res,jac=None)
    integrator = integrator.set_integrator(name,**params)
    integrator = integrator.set_initial_value(y0,yprime0, t=0.0)
    y1, y1prime = integrator.solve(t1,step=0,relax=0)
    flag = integrator.successful()

res and jac need to have the signature as required by the integrator name. If
you need to pass extra arguments to jac, use eg a python class method : 
    problem = Myproblem()
    integrator = dae(problem.res,problem.jac)
Allowing the extra parameters to be kept in the Myproblem class
"""

integrator_info = \
"""
Available integrators
---------------------

ddaspk
~~~~~~

This code solves a system of differential/algebraic equations of the form 
G(t,y,y') = 0 , using a combination of Backward Differentiation Formula 
(BDF) methods and a choice of two linear system solution methods: direct 
(dense or band) or Krylov (iterative). 
Krylov is not supported from within scipy. In order to support it, a new
interface should be created ddaspk_krylov, with a different signature,
reflecting the changes needed.

Source: http://www.netlib.org/ode/ddaspk.f

This integrator accepts the following parameters in set_integrator()
method of the ode class:

- atol : float or sequence of length i
  absolute tolerance for solution
- rtol : float or sequence of length i
  relative tolerance for solution
- lband : None or int
- uband : None or int
  Jacobian band width, jac[i,j] != 0 for i-lband <= j <= i+uband.
  Setting these requires your jac routine to return the jacobian
  in packed format, jac_packed[i-j+lband, j] = jac[i,j].
- tcrit : None or float. If given, tcrit is a critical time point
  beyond which no integration occurs
- nsteps : int
  Maximum number of (internally defined) steps allowed during one
  call to the solver.
- first_step : float
  Set initial stepsize. DAE solver can suffer on the first step, set this
  to circumvent this.
- max_step : float
  Limits for the step sizes used by the integrator. This overrides the
  internal value
- order : int
  Maximum order used by the integrator, >=1,  <= 5 for BDF.
  5 is the default
- enforce_nonnegativity: bool
  Enforce the nonnegativity of Y during integration
  Note: best is to run code first with no condition
- compute_initcond: None or 'yprime0' or 'yode0'
  DDASPK may be able to compute the initial conditions if you do not know them
  precisely. 
  If yprime0, then y0 will be calculated
  If yode0, then the differential variables will be used to solve for the 
    algebraic variables and the derivative of the differential variables. 
    Which are the algebraic variables must be indicated with algebraic_var method
- constraint_init: bool
  Enforce the constraint checks of Y during initial condition computation
  Note: try first with no constraints
- constraint_type: if constraint_init, give an integer array with for every
  unknown the specific condition to check: 
       1: y0[i] >= 0 
       2: y0[i] >  0
      -1: y0[i] <= 0
      -2: y0[i] <  0
       0: y0[i] not constrained
  Alternatively, pass only one integer that then applies to all unknowns
- algebraic_var: integer array of length the number of unknowns, indicating the 
  algebraic variables in y. Use -1 to indicate an algebraic variable, and +1 for
  a differential variable.

lsodi
~~~~~
Not included, should be easy based on patch at 
                 http://www.scipy.org/scipy/scipy/ticket/615
Adda should however be a parameter passed to the set_integrator function.

ddaskr  
~~~~~~
Not included, starting hints:
                 http://osdir.com/ml/python.f2py.user/2005-07/msg00014.html

ida/pysundials
~~~~~~~~~~~~~~
Not included.
ida is the successor of ddaspk, written in C and part of sundials. 
A python interface exists as pysundials, which allows numpy input arrays. 
It should be possible to add here as a backend by checking if 'import pysundials'
succeeds.

Modified Extended Backward Differentiation Formulae (MEBDF)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Not included. Fortran codes: http://www.ma.ic.ac.uk/~jcash/IVP_software/readme.html
"""

__doc__ += integrator_info

#
# How to define a new dae solver:
# ===============================
#
# class mydaeint(DaeIntegratorBase):
#
#     runner = <dae function> or None
#
#     def __init__(self,...):                           # required
#         <initialize>
#
#     def reset(self,n,has_jac):                        # optional
#         # n - the size of the problem (number of equations)
#         # has_jac - whether user has supplied its own routine for Jacobian
#         <allocate memory,initialize further>
#
#     def run(self,res,jac,y0,yprime0,t0,t1,res_params,jac_params): # required
#         # this method is called to integrate from t=t0 to t=t1
#         # with initial condition y0 yprime0. 
#         #res and jac are user-supplied functions
#         # that define the problem. res_params,jac_params are additional
#         # arguments
#         # to these functions.
#         <calculate y1>
#         if <calculation was unsuccesful>:
#             self.success = 0
#         return t1,y1,y1prime
#
#     # In addition, one can define step() and run_relax() methods (they
#     # take the same arguments as run()) if the integrator can support
#     # these features (see IntegratorBase doc strings).
#
# if mydaeint.runner:
#     DaeIntegratorBase.integrator_classes.append(myodeint)

__all__ = ['dae']
__version__ = "$Id$"
__docformat__ = "restructuredtext en"

from numpy import asarray, array, zeros, sin, int32, isscalar
import re, sys

#------------------------------------------------------------------------------
# User interface
#------------------------------------------------------------------------------

class dae(object):
    """\
A generic interface class to differential algebraic equation solvers.

See also
--------
odeint : an ODE integrator with a simpler interface based on lsoda from ODEPACK
ode : class around vode ODE integrator

Examples
--------
DAE arise in many applications of dynamical systems, as well as in 
discritisations of PDE (eg moving mesh combined with method of 
lines). 
As an easy example, consider the simple oscillator, which we write as 
G(y,y',t) = 0 instead of the normal ode, and solve as a DAE.

>>>from numpy import (arange, zeros, array, dot, sqrt, cos, sin, allclose)
>>>from scipy.integrate import dae
>>>class SimpleOscillator():
    #Free vibration of a simple oscillator::
    #    m \ddot{u} + k u = 0, u(0) = u_0, \dot{u}(0)=\dot{u}_0
    #Solution::
    #    u(t) = u_0*cos(sqrt(k/m)*t)+\dot{u}_0*sin(sqrt(k/m)*t)/sqrt(k/m)
    stop_t  = [2.09]
    u0      = 1.
    dotu0   = 0.1

    k = 4.0
    m = 1.0
    z0      = array([dotu0, u0], float)    #Free vibration of a simple oscillator::
    #    m \ddot{u} + k u = 0, u(0) = u_0, \dot{u}(0)=\dot{u}_0
    #Solution::
    #    u(t) = u_0*cos(sqrt(k/m)*t)+\dot{u}_0*sin(sqrt(k/m)*t)/sqrt(k/m)
    stop_t  = [2.09, 3.]
    u0      = 1.
    dotu0   = 0.1

    k = 4.0
    m = 1.0
    z0      = array([dotu0, u0], float)
    zprime0 = array([-k*u0, dotu0], float)

    def res(self, t, z, zp):
        tmp1 = zeros((2,2), float)
        tmp2 = zeros((2,2), float)
        tmp1[0,0] = self.m
        tmp1[1,1] = 1.
        tmp2[0,1] = self.k
        tmp2[1,0] = -1.
        return dot(tmp1, zp)+dot(tmp2, z)
    def solution(self, t):
        omega = sqrt(self.k / self.m)
        u = self.z0[1]*cos(omega*t)+self.z0[0]*sin(omega*t)/omega

>>> problem = SimpleOscillator()
>>> ig = dae(problem.res, None)
>>> ig.set_integrator('ddaspk')
>>> ig.set_initial_value(problem.z0, problem.zprime0,  t=0.0)
>>> z = [0]*len(problem.stop_t); zprime = [0]*len(problem.stop_t)
>>> i=0
>>> for time in problem.stop_t:
      z[i],  zprime[i] = ig.solve(time)
      i += 1
      assert ig.successful(), (problem,)
>>> for (time, zv) in zip(problem.stop_t, z):
      print 'calc', zv[1], ' ?? == ?? ', problem.solution(time)

"""

    __doc__ += integrator_info

    def __init__(self, res, jac=None):
        """
        Define equation res = G(t,y,y') which can eg be G = f(y,t) - A y' when 
        solving A y' = f(y,t), 
        and where (optional) jac is the jacobian matrix of the nonlinear system
        see fortran source code), so d res/dy + scaling * d res/dy'.

        Parameters
        ----------
        res : res(t, y, yprime, *res_args)
            Residual of the DAE. t is a scalar, y.shape == (n,), 
            yprime.shape == (n,)
            res_args is determined by the solver backend, set it as required by
            the backend you use
            res should return delta, status
            delta should be an array of the residuals, and status: 
              0 : continue
              -1: Illigal input, try again
              -2: Illigal input, stop
             It is not guaranteed that a solver takes this status into account 
        jac : jac(t, y, yprime, *jac_args)
            Jacobian of the rhs, typically 
                jac[i,j] = d res[i] / d y[j] + scaling *  d res[i] / d yprime[j]
            jac_args is determined by the solver backend, set it as required by
            the backend you use
        """
        self.res = res
        self.jac  = jac
        self.y = []
        self.yprime = []

    def set_initial_value(self, y, yprime, t=0.0):
        """Set initial conditions y(t) = y, y'(t) = yprime """
        if isscalar(y):
            y = [y]
        if isscalar(yprime):
            yprime = [yprime]
        n_prev = len(self.y)
        if not n_prev:
            self.set_integrator('') # find first available integrator
        self.y = asarray(y, self._integrator.scalar)
        self.yprime = asarray(yprime, self._integrator.scalar)
        self.t = t
        self._integrator.reset(len(self.y),self.jac is not None)
        return self

    def set_integrator(self, name, **integrator_params):
        """
        Set integrator by name.

        Parameters
        ----------
        name : str
            Name of the integrator
        integrator_params
            Additional parameters for the integrator.
        """
        integrator = find_dae_integrator(name)
        if integrator is None:
            print 'No integrator name match with %s or is not available.'\
                  %(`name`)
        else:
            self._integrator = integrator(**integrator_params)
            if not len(self.y):
                self.t = 0.0
                self.y = array([0.0], self._integrator.scalar)
        return self

    def solve(self, t, step=0, relax=0):
        """Find y=y(t), and y'=y'(t) solution of the dae. 
           If step, then one internal step is taken (use this if much output is
                    needed). 
           If relax, then the solution is returned based on the first internal 
                    point at or over the requested endtime
        """
        if step and self._integrator.supports_step:
            mth = self._integrator.step
        elif relax and self._integrator.supports_run_relax:
            mth = self._integrator.run_relax
        else:
            mth = self._integrator.run
        self.y, self.yprime, self.t = mth(self.res,
                            self.jac or (lambda :None),
                            self.y,self.yprime,self.t,t)
        return self.y,  self.yprime

    def successful(self):
        """Check if integration was successful."""
        try: self._integrator
        except AttributeError: self.set_integrator('')
        return self._integrator.success==1

#------------------------------------------------------------------------------
# DAE integrators
#------------------------------------------------------------------------------

def find_dae_integrator(name):
    for cl in DaeIntegratorBase.integrator_classes:
        if re.match(name,cl.__name__,re.I):
            return cl
    return

class DaeIntegratorBase(object):

    runner = None            # runner is None => integrator is not available
    success = None           # success==1 if integrator was called successfully
    supports_run_relax = None
    supports_step = None
    integrator_classes = []
    scalar = float

    def reset(self,n,has_jac):
        """Prepare integrator for call: allocate memory, set flags, etc.
        n - number of equations
        has_jac - if user has supplied function for evaluating Jacobian.
        """

    def run(self,res,jac,y0,yprime0,t0,t1):
        """Integrate from t=t0 to t=t1 using y0 and yprime0as an initial 
        condition.
        Return 4-tuple (y1,y1prime,t1,istate) where y1,y1prime is the result 
        and t=t1 defines the stoppage coordinate of the result.
        """
        raise NotImplementedError,\
        'all daeintegrators must define run(res,jac,t0,t1,y0,yprime0,'
        'res_params,jac_params)'

    def step(self,res,jac,y0,yprime0,t0,t1):
        """Make one integration step and return (y1,t1)."""
        raise NotImplementedError,'%s does not support step() method' %\
              (self.__class__.__name__)

    def run_relax(self,res,jac,y0,yprime0,t0,t1):
        """Integrate from t=t0 to t>=t1 and return (y1,t)."""
        raise NotImplementedError,'%s does not support run_relax() method' %\
              (self.__class__.__name__)

    #XXX: __str__ method for getting visual state of the integrator

class ddaspk(DaeIntegratorBase):
    try:
        import ddaspk as _ddaspk
    except ImportError:
        print sys.exc_value
        _ddaspk = None
    runner = getattr(_ddaspk,'ddaspk',None)

    messages = { 1: 'A step was successfully taken in the '
                    'intermediate-output mode.  The code has not '
                    'yet reached TOUT.', 
                 2: 'The integration to TSTOP was successfully '
                    'completed (T = TSTOP) by stepping exactly to TSTOP.', 
                 3: 'The integration to TOUT was successfully '
                    'completed (T = TOUT) by stepping past TOUT. '
                    'Y(*) and YPRIME(*) are obtained by interpolation.', 
                 4: 'The initial condition calculation, with '
                    'INFO(11) > 0, was successful, and INFO(14) = 1. '
                    'No integration steps were taken, and the solution '
                    'is not considered to have been started.', 
                -1: 'A large amount of work has been expended (about 500 steps)',
                -2: 'Excess accuracy requested. (Tolerances too small.)',
                -3: 'The local error test cannot be satisfied because you '
                    'specified a zero component in ATOL and the corresponding'
                    ' computed solution component is zero.  Thus, a pure'
                    ' relative error test is impossible for this component.',
                -5: 'Repeated failures in the evaluation or processing of the'
                    ' preconditioner (in JAC)',
                -6: 'repeated error test failures on the last attempted step)', 
                -7: 'The nonlinear system solver in the time integration could'
                    ' not converge.',
                -8: 'The matrix of partial derivatives appears to be singular'
                    ' (direct method).', 
                -9: 'The nonlinear system solver in the time integration'
                    'failed to achieve convergence, and there were repeated '
                    'error test failures in this step.', 
                -10:'The nonlinear system solver in the time integration failed'
                    ' to achieve convergence because IRES was equal to -1.', 
                -11:'IRES = -2 was encountered and control is'
                    'being returned to the calling program.', 
                -12:'Failed to compute the initial Y, YPRIME.', 
                -13:"Unrecoverable error encountered inside user's"
                    "PSOL routine, and control is being returned to"
                    "the calling program.", 
                -14:'The Krylov linear system solver could not '
                    'achieve convergence.', 
                -33:'The code has encountered trouble from which'
                   ' it cannot recover.  A message is printed'
                   ' explaining the trouble and control is returned'
                   ' to the calling program.  For example, this occurs'
                   ' when invalid input is detected.', 
                }
    supports_run_relax = 0
    supports_step = 1

    def __init__(self,
                 rtol=1e-6,atol=1e-12,
                 lband=None,uband=None,
                 tcrit=None, 
                 order = 5,
                 nsteps = 500,
                 max_step = 0.0, # corresponds to infinite
                 first_step = 0.0, # determined by solver
                 enforce_nonnegativity=False, 
                 nonneg_type=None, 
                 compute_initcond=None,
                 constraint_init=False, 
                 constraint_type=None, 
                 algebraic_var=None,  
                 ):

        self.rtol = rtol
        self.atol = atol
        self.mu = uband
        self.ml = lband

        self.tcrit = tcrit
        if order > 5 or order < 1:
            raise ValueError, 'order should be >=1, <=5'
        self.order = order
        self.nsteps = nsteps
        self.max_step = max_step
        self.first_step = first_step
        self.nonneg =0 
        if enforce_nonnegativity and constraint_init: self.nonneg = 3
        elif enforce_nonnegativity: self.nonneg = 2
        elif constraint_init: self.nonneg = 1
        if (self.nonneg == 1 or self.nonneg == 3) and constraint_type is None:
            raise ValueError, 'Give type of init cond contraint as '\
                              'an int array (>=0, >0, <=0, <0) or as int'
        else: self.constraint_type = constraint_type
        if compute_initcond is None: self.compute_initcond = 0
        elif re.match(compute_initcond,r'yprime0',re.I): 
            self.compute_initcond = 2
        elif re.match(compute_initcond,r'yode0',re.I): self.compute_initcond = 1
        else: raise ValueError,'Unknown init cond calculation method %s' %(
                                                            compute_initcond)
        if self.compute_initcond == 1 and algebraic_var is None:
            raise ValueError, 'Give integer array indicating which are the '\
                              'algebraic variables, +1 for diffential var, '\
                              '-1 for algebraic var'
        self.algebraic_var = algebraic_var
        self.success = 1

    def reset(self,n,has_jac):
        # Calculate parameters for Fortran subroutine ddaspk.
        self.info = zeros((20,), int32)  # default is all info=0
        if (isscalar(self.atol) <> isscalar(self.rtol)) or (
               not isscalar(self.atol) and len(self.atol) <> len(self.rtol)):
            raise ValueError,'atol (%s) and rtol (%s) must be both scalar or'\
                    ' both arrays of length %s' % (self.atol, self.rtol, n)
        if not isscalar(self.atol):
            self.info[1] = 1
        if has_jac:
            self.info[4] = 1
        if self.mu is not None or self.ml is not None:
            if self.mu is None: self.mu = 0
            if self.ml is None: self.ml = 0
            self.info[5] = 1
        lrw = 50 + max(self.order+4,7)*n
        if self.info[5]==0: lrw += pow(n, 2)
        elif self.info[4]==0: 
            lrw += (2*self.ml+self.mu+1)*n + 2*(n/(self.ml+self.mu+1)+1)
        else: lrw += (2*self.ml+self.mu+1)*n
        rwork = zeros((lrw,), float)
        liw = 40 + n
        if self.nonneg in [1, 3]: liw += n
        if self.compute_initcond: liw += n
        iwork = zeros((liw,), int32)
        if self.tcrit is not None:
            self.info[3] = 1
            rwork[0] = self.tcrit
        if self.max_step > 0.0 :
            self.info[6] = 1
            rwork[1] = self.max_step
        if self.first_step > 0.0 :
            self.info[7] = 1
            rwork[2] = self.first_step
        self.rwork = rwork
        if self.ml is not None:
            iwork[0] = self.ml
        if self.mu is not None:
            iwork[1] = self.mu
        if self.order < 5 :
            self.info[8] = 1
            iwork[2] = self.order
        iwork[5] = self.nsteps
        iwork[6] = 2           # mxhnil
        self.info[9] = self.nonneg
        lid = 40
        if self.info[9]==1 or self.info[9]==3 :
            lid = 40 + n
            if isscalar(self.constraint_type): 
                iwork[40:lid]=self.constraint_type
            else: iwork[40:lid]=self.constraint_type[:]
        self.info[10]=self.compute_initcond
        if self.info[10] in [1, 2]:
            iwork[lid:lid+n] = self.algebraic_var[:]
        ## some overrides that one might want
        # self.info[17] = 1  # minimal printing inside init cond calc
        # self.info[17] = 2  # full printing inside init cond calc
        self.iwork = iwork
        
        self.call_args = [self.info,self.rtol,self.atol,self.rwork,self.iwork]
        self.success = 1

    def _run(self, states, *args):
        # args are: res,jac,y0,yprime0,t0,t1,res_params,jac_params
        y1,y1prime,t,istate = self.runner(*(args[:6]+tuple(self.call_args)))
        if istate <0:
            print 'ddaspk:',self.messages.get(istate,'Unexpected istate=%s' % 
                                              istate)
            self.success = 0
        elif istate not in states:
            print 'ddaspk: Run successfull. Unexpected istate=%s, stopping' % \
                                            istate
            print self.messages.get(istate, 'Unknown istate=%s' % istate)
            self.success = 0
        return y1,y1prime,t

    def run(self, *args):
        return self._run([2, 3], *args)

    def step(self,*args):
        self.info[2] = 1
        r = self._run([1, 2], *args)
        self.info[2] = 0
        return r

if ddaspk.runner:
    DaeIntegratorBase.integrator_classes.append(ddaspk)
