# Authors: B. Malengier, russel (scipy trac)
"""
Tests for differential algebraic equation solvers.
"""
import numpy

from numpy import (arange, zeros, array, dot, sqrt, cos, sin, allclose)

from numpy.testing import *
from scipy.integrate import ode
from scikits.odes import dae

class TestDae(TestCase):
    """
    Check integrate.dae
    """
    def _do_problem(self, problem, integrator,  **integrator_params):
        jac = None
        if hasattr(problem, 'jac'):
            jac = problem.jac

        ig = dae(problem.res, jac)
        ig.set_integrator(integrator,
                          **integrator_params)
        ig.set_initial_value(problem.z0, problem.zprime0,  t=0.0)
        z = [0]*len(problem.stop_t)
        zprime = [0]*len(problem.stop_t)
        i=0
        for time in problem.stop_t:
            z[i],  zprime[i] = ig.solve(time)
            i += 1
            assert ig.successful(), (problem,)
        assert problem.verify(array(z), array(zprime),  problem.stop_t), \
                    (problem,)

    def test_ddaspk(self):
        """Check the ddaspk solver"""
        for problem_cls in PROBLEMS:
            problem = problem_cls()
            self._do_problem(problem, 'ddaspk', **problem.ddaspk_pars)

#------------------------------------------------------------------------------
# Test problems
#------------------------------------------------------------------------------

class DAE:
    """
    DAE problem
    """
    stop_t  = [1]
    z0      = []
    zprime0 =  []

    atol    = 1e-6
    rtol    = 1e-5

    ddaspk_pars = {}

class SimpleOscillator(DAE):
    r"""
    Free vibration of a simple oscillator::
        m \ddot{u} + k u = 0, u(0) = u_0, \dot{u}(0)=\dot{u}_0
    Solution::
        u(t) = u_0*cos(sqrt(k/m)*t)+\dot{u}_0*sin(sqrt(k/m)*t)/sqrt(k/m)
    """
    stop_t  = [2 + 0.09,  3.]
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

    def verify(self, zs, zps, t):
        omega = sqrt(self.k / self.m)
        ok = True
        for (z, zp, time) in zip(zs, zps, t):
            u = self.z0[1]*cos(omega*time)+self.z0[0]*sin(omega*time)/omega
            ok = ok and allclose(u, z[1], atol=self.atol, rtol=self.rtol) and \
            allclose(z[0], zp[1], atol=self.atol, rtol=self.rtol)
        return ok

class SimpleOscillatorJac(SimpleOscillator):
    def jac(self, t, y, yp, cj):
        """Jacobian[i,j] is dRES(i)/dY(j) + CJ*dRES(i)/dYPRIME(j)"""
        jc = zeros((len(y), len(y)), float)
        cj_in = cj
        jc[0, 0] = self.m*cj_in ;jc[0, 1] = self.k
        jc[1, 0] = -1       ;jc[1, 1] = cj_in;  
        print 'jc at', t, cj,  jc
        return jc

class StiffVODECompare(DAE):
    r"""
    We create a stiff problem, obtain the vode solution, and compare with 
    dae solution
    Correct solution with runga-kutta 45:
     [t = 0.4, y0(t) = 0.985172121250895372, y1(t) = 0.0000338791735424692934, 
               y2(t) = 0.0147939995755618956]
     [t = 4., y0(t) = 0.905519130228504610, y1(t) = 0.0000224343714361267687, 
               y2(t) = 0.0944584354000592570]
    """
    z0      = array([1., 0., 0.], float)
    zprime0 = array([-0.04, 0.04, 0.], float)

    atol    = 1e-4
    rtol    = 1e-4

    def f_vode(self, t, y):
        ydot0 = -0.04*y[0] + 1e4*y[1]*y[2]
        ydot2 = 3e7*y[1]*y[1]
        ydot1 = -ydot0-ydot2
        return array([ydot0,ydot1,ydot2])

    def jac_vode(self, t, y):
        jc = [[-0.04,1e4*y[2]          ,1e4*y[1]],
              [0.04 ,-1e4*y[2]-6e7*y[1],-1e4*y[1]],
              [0.0    ,6e7*y[1]           ,0.0]]
        return array(jc)

    def __init__(self):
        """We obtain the vode solution first"""
        r = ode(self.f_vode,self.jac_vode).set_integrator('vode',
                                  rtol=[1e-4,1e-4,1e-4], 
                                  atol=[1e-8,1e-14,1e-6],
                                  method='bdf',
                                  )
        r.set_initial_value([1.,0.,0.])
        nr = 4
        self.sol = zeros((nr, 3))
        self.stop_t = [0.4]*nr
        for i in range(nr-1):
            self.stop_t[i+1] = 10 * self.stop_t[i]
        i=0
        for time in self.stop_t:
            r.integrate(time)
            self.sol[i] = r.y
            i +=1

        #we need to activate some extra parameters in the solver
        #order par is rtol,atol,lband,uband,tcrit,order,nsteps,
        #         max_step,first_step,enforce_nonnegativity,nonneg_type, 
        #         compute_initcond,constraint_init,constraint_type,algebraic_var
        self.ddaspk_pars = {'rtol' : [1e-4,1e-4,1e-4], 
                            'atol' : [1e-8,1e-14,1e-6], 
                           }

    def res(self, t, y, yp):
        eq0 = yp[0] + 0.04*y[0] - 1e4*y[1]*y[2]
        eq2 = yp[2] - 3e7*y[1]*y[1]
        eq1 = yp[1] +yp[0]+yp[2]
        return array([eq0,eq1,eq2])

    def verify(self, y, yp, t):
        return allclose(self.sol, y, atol=self.atol, rtol=self.rtol)

PROBLEMS = [SimpleOscillator, StiffVODECompare,  
            SimpleOscillatorJac ]

#------------------------------------------------------------------------------

if __name__ == "__main__":
    run_module_suite()