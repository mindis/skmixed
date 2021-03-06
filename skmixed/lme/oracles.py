# This code implements linear mixed-effects oracle as a subroutine for skmixed's subroutines.
# Copyright (C) 2020 Aleksei Sholokhov, aksh@uw.edu
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


from typing import Callable

import numpy as np
from scipy.linalg.lapack import get_lapack_funcs

from skmixed.lme.problems import LinearLMEProblem


class LinearLMEOracle:
    """
    Implements Linear Mixed-Effects Model functional for given problem.

    The model is::

        Y_i = X_i*β + Z_i*u_i + 𝜺_i,

        where

        u_i ~ 𝒩(0, diag(𝛄)),

        𝜺_i ~ 𝒩(0, Λ)

    The problem should be provided as LinearLMEProblem.

    """

    def __init__(self, problem: LinearLMEProblem):
        """
        Creates an oracle on top of the given problem

        Parameters
        ----------
        problem : LinearLMEProblem
            set of data and answers. See docs for LinearLMEProblem class for more details.
        """

        self.problem = problem
        self.omega_cholesky_inv = []
        self.omega_cholesky = []
        self.gamma = None
        beta_to_gamma_map = np.zeros(self.problem.num_fixed_effects)
        beta_counter = 0
        gamma_counter = 0
        for label in self.problem.column_labels:
            if label == 1:
                beta_to_gamma_map[beta_counter] = -1
                beta_counter += 1
            elif label == 2:
                gamma_counter += 1
            elif label == 3:
                beta_to_gamma_map[beta_counter] = gamma_counter
                beta_counter += 1
                gamma_counter += 1
            else:
                continue
        self.beta_to_gamma_map = beta_to_gamma_map

    def _recalculate_cholesky(self, gamma: np.ndarray):
        """
        Recalculates Cholesky factors of all Ω_i's when gamma changes.

        Supplementary subroutine which recalculates Cholesky decompositions and their inverses of matrices Ω_i
        when 𝛄 (estimated set of covariances for random effects) changes:

        Ω_i = Z_i*diag(𝛄)*Z_i^T + Λ_i = L_i*L_i^T

        Parameters
        ----------
        gamma : np.ndarray, shape=[k]
            vector of covariances for random effects

        Returns
        -------
            None :
                if all the Cholesky factors were updated and stored successfully, otherwise raises and error
        """

        if (self.gamma != gamma).any():
            self.omega_cholesky = []
            self.omega_cholesky_inv = []
            gamma_mat = np.diag(gamma)
            invert_upper_triangular: Callable[[np.ndarray], np.ndarray] = get_lapack_funcs("trtri")
            for x, y, z, stds in self.problem:
                omega = z.dot(gamma_mat).dot(z.T) + np.diag(stds)
                L = np.linalg.cholesky(omega)
                L_inv = invert_upper_triangular(L.T)[0].T
                self.omega_cholesky.append(L)
                self.omega_cholesky_inv.append(L_inv)
            self.gamma = gamma
        return None

    def loss(self, beta: np.ndarray, gamma: np.ndarray, **kwargs) -> float:
        """
        Returns the loss function value ℒ(β, 𝛄).

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
            result : float
                The value of the loss function: ℒ(β, 𝛄)
        """

        result = 0
        self._recalculate_cholesky(gamma)
        for (x, y, z, stds), L_inv in zip(self.problem, self.omega_cholesky_inv):
            xi = y - x.dot(beta)
            result += 1 / 2 * np.sum(L_inv.dot(xi) ** 2) - np.sum(np.log(np.diag(L_inv)))
        return result

    def gradient_gamma(self, beta: np.ndarray, gamma: np.ndarray, **kwargs) -> np.ndarray:
        """
        Returns the gradient of the loss function with respect to gamma: ∇_𝛄[ℒ](β, 𝛄)

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
            grad_gamma: np.ndarray, shape = [k]
                The gradient of the loss function with respect to gamma: ∇_𝛄[ℒ](β, 𝛄)
        """

        self._recalculate_cholesky(gamma)
        grad_gamma = np.zeros(len(gamma))
        for (x, y, z, stds), L_inv in zip(self.problem, self.omega_cholesky_inv):
            xi = y - x.dot(beta)
            Lz = L_inv.dot(z)
            grad_gamma += 1 / 2 * np.sum(Lz ** 2, axis=0) - 1 / 2 * Lz.T.dot(L_inv.dot(xi)) ** 2
        return grad_gamma

    def hessian_gamma(self, beta: np.ndarray, gamma: np.ndarray, **kwargs) -> np.ndarray:
        """
        Returns the Hessian of the loss function with respect to gamma ∇²_𝛄[ℒ](β, 𝛄).

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
            hessian: np.ndarray, shape = [k, k]
                Hessian of the loss function with respect to gamma ∇²_𝛄[ℒ](β, 𝛄).
        """
        self._recalculate_cholesky(gamma)
        num_random_effects = self.problem.num_random_effects
        hessian = np.zeros(shape=(num_random_effects, num_random_effects))
        for (x, y, z, stds), L_inv in zip(self.problem, self.omega_cholesky_inv):
            xi = y - x.dot(beta)
            Lz = L_inv.dot(z)
            Lxi = L_inv.dot(xi).reshape((len(xi), 1))
            hessian += (-Lz.T.dot(Lz) + 2 * (Lz.T.dot(Lxi).dot(Lxi.T).dot(Lz))) * (Lz.T.dot(Lz))
        return 1 / 2 * hessian

    def optimal_beta(self, gamma: np.ndarray, _dont_solve_wrt_beta=False, **kwargs):
        """
        Returns beta (vector of estimations of fixed effects) which minimizes loss function for a fixed gamma.

        The algorithm for computing optimal beta is::

            kernel = ∑X_i^TΩ_iX_i

            tail = ∑X_i^TΩ_iY_i

            β = (kernel)^{-1}*tail

        It's available almost exclusively in linear models. In general one should use gradient_beta and do iterative
        minimization instead.

        Parameters
        ----------
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        _dont_solve_wrt_beta : bool, Optional
            If true, then it does not perform the outer matrix inversion and returns the (kernel, tail) instead.
            It's left here for the purposes of use in child classes where both the kernel and the tail should be
            adjusted to account for regularization.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
        beta: np.ndarray, shape = [n]
            Vector of optimal estimates of the fixed effects for given gamma.
        """
        self._recalculate_cholesky(gamma)
        kernel = 0
        tail = 0
        for (x, y, z, stds), L_inv in zip(self.problem, self.omega_cholesky_inv):
            Lx = L_inv.dot(x)
            kernel += Lx.T.dot(Lx)
            tail += Lx.T.dot(L_inv.dot(y))
        if _dont_solve_wrt_beta:
            return kernel, tail
        else:
            return np.linalg.solve(kernel, tail)

    def optimal_random_effects(self, beta: np.ndarray, gamma: np.ndarray, **kwargs) -> np.ndarray:
        """
        Returns set of optimal random effects estimations for given beta and gamma.

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
        u : np.ndarray, shape = [m, k]
            Set of optimal random effects estimations for given beta and gamma

        """

        random_effects = []
        for (x, y, z, stds), L_inv in zip(self.problem, self.omega_cholesky_inv):
            xi = y - x.dot(beta)
            stds_inv_mat = np.diag(1 / stds)
            # If the variance of R.E. is 0 then the R.E. is 0, so we take it into account separately
            # to keep matrices invertible.
            mask = np.abs(gamma) > 1e-10
            z_masked = z[:, mask]
            gamma_masked = gamma[mask]
            u_nonzero = np.linalg.solve(np.diag(1 / gamma_masked) + z_masked.T.dot(stds_inv_mat).dot(z_masked),
                                        z_masked.T.dot(stds_inv_mat).dot(xi)
                                        )
            u = np.zeros(len(gamma))
            u[mask] = u_nonzero
            random_effects.append(u)
        return np.array(random_effects)


class LinearLMEOracleRegularized(LinearLMEOracle):
    """
    Implements Regularized Linear Mixed-Effects Model functional for given problem::

        Y_i = X_i*β + Z_i*u_i + 𝜺_i,

        where

        β ~ 𝒩(tb, 1/lb),

        ||tβ||_0 = nnz(β) <= nnz_tbeta,

        u_i ~ 𝒩(0, diag(𝛄)),

        𝛄 ~ 𝒩(t𝛄, 1/lg),

        ||t𝛄||_0 = nnz(t𝛄) <= nnz_tgamma,

        𝜺_i ~ 𝒩(0, Λ)

    Here tβ and t𝛄 are single variables, not multiplications (e.g. not t*β). This oracle is designed for
    a solver (LinearLMESparseModel) which searches for a sparse solution (tβ, t𝛄) with at most k and j <= k non-zero
    elements respectively. For more details, see the documentation for LinearLMESparseModel.

    The problem should be provided as LinearLMEProblem.

    """

    def __init__(self, problem: LinearLMEProblem, lb=0.1, lg=0.1, nnz_tbeta=3, nnz_tgamma=3):
        """
        Creates an oracle on top of the given problem. The problem should be in the form of LinearLMEProblem.

        Parameters
        ----------
        problem: LinearLMEProblem
            The set of data and answers. See the docs for LinearLMEProblem for more details.
        lb : float
            Regularization coefficient (inverse std) for ||β - tβ||^2
        lg : float
            Regularization coefficient (inverse std) for ||𝛄 - t𝛄||^2
        nnz_tbeta : int
            Number of non-zero elements allowed in tβ
        nnz_tgamma : int
            Number of non-zero elements allowed in t𝛄
        """

        super().__init__(problem)
        self.lb = lb
        self.lg = lg
        self.k = nnz_tbeta
        self.j = nnz_tgamma

    def optimal_beta(self, gamma: np.ndarray, tbeta: np.ndarray = None, _dont_solve_wrt_beta=False, **kwargs):
        """
        Returns beta (vector of estimations of fixed effects) which minimizes loss function for a fixed gamma.

        The algorithm for computing optimal beta is::

            kernel = ∑X_i^TΩ_iX_i

            tail = ∑X_i^TΩ_iY_i

            β = (kernel + I*lb)^{-1}*(tail + lb*tbeta)

        It's available almost exclusively in linear models. In general one should use gradient_beta and do iterative
        minimization instead.

        Parameters
        ----------
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        tbeta : np.ndarray, shape = [n]
            Vector of (nnz_tbeta)-sparse estimates for fixed effects.
        _dont_solve_wrt_beta : bool, Optional
            If true, then it does not perform the outer matrix inversion and returns the (kernel, tail) instead.
            It's left here for the purposes of use in child classes where both the kernel and the tail should be
            adjusted to account for regularization.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
        beta: np.ndarray, shape = [n]
            Vector of optimal estimates of the fixed effects for given gamma.
        """
        kernel, tail = super().optimal_beta(gamma, _dont_solve_wrt_beta=True, **kwargs)
        if _dont_solve_wrt_beta:
            return kernel, tail
        return np.linalg.solve(self.lb * np.eye(self.problem.num_fixed_effects) + kernel, self.lb * tbeta + tail)

    @staticmethod
    def _take_only_k_max(x: np.ndarray, k: int, **kwargs):
        """
        Returns a vector b which consists of k largest elements of x (at the same places) and zeros everywhere else.

        Parameters
        ----------
        x : np.ndarray, shape = [n]
            Vector which we take largest elements from.
        k : int
            How many elements we take from x
        kwargs :
            Not used, left for future and for passing debug/experimental parameters.

        Returns
        -------
        b : np.ndarray, shape = [n]
            A vector which consists of k largest elements of x (at the same places) and zeros everywhere else.
        """

        b = np.zeros(len(x))
        idx_k_max = np.abs(x).argsort()[-k:]
        b[idx_k_max] = x[idx_k_max]
        return b

    def optimal_tbeta(self, beta: np.ndarray, **kwargs):
        """
        Returns tbeta which minimizes the loss function with all other variables fixed.

        It is a projection of beta on the sparse subspace with no more than k elements, which can be constructed by
        taking k largest elements from beta and setting the rest to be 0.

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters.

        Returns
        -------
        tbeta : np.ndarray, shape = [n]
            Minimizer of the loss function w.r.t tbeta with other arguments fixed.
        """

        return self._take_only_k_max(beta, self.k, **kwargs)

    def loss(self, beta: np.ndarray, gamma: np.ndarray, tbeta: np.ndarray = None, tgamma: np.ndarray = None, **kwargs):
        """
        Returns the loss function value ℒ(β, 𝛄) + lb/2*||β - tβ||^2 + lg/2*||𝛄 - t𝛄||^2

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        tbeta : np.ndarray, shape = [n]
            Vector of (nnz_tbeta)-sparse estimates of fixed effects.
        tgamma : np.ndarray, shape = [k]
            Vector of (nnz_tgamma)-sparse estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters.

        Returns
        -------
            result : float
                The value of the loss function: ℒ(β, 𝛄) + lb/2*||β - tβ||^2 + lg/2*||𝛄 - t𝛄||^2
        """

        return (super().loss(beta, gamma, **kwargs)
                + self.lb / 2 * sum((beta - tbeta) ** 2)
                + self.lg / 2 * sum((gamma - tgamma) ** 2))

    def gradient_gamma(self, beta: np.ndarray, gamma: np.ndarray, tgamma: np.ndarray = None, **kwargs) -> np.ndarray:
        """
        Returns the gradient of the loss function with respect to gamma: grad_gamma =  ∇_𝛄[ℒ](β, 𝛄) + lg*(𝛄 - t𝛄)

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        tgamma : np.ndarray, shape = [k]
            Vector of (nnz_tgamma)-sparse covariance estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
            grad_gamma: np.ndarray, shape = [k]
                The gradient of the loss function with respect to gamma: grad_gamma = ∇_𝛄[ℒ](β, 𝛄) + lg*(𝛄 - t𝛄)
        """

        return super().gradient_gamma(beta, gamma, **kwargs) + self.lg * (gamma - tgamma)

    def hessian_gamma(self, beta: np.ndarray, gamma: np.ndarray, **kwargs) -> np.ndarray:
        """
        Returns the Hessian of the loss function with respect to gamma: ∇²_𝛄[ℒ](β, 𝛄) + lg*I.

        Parameters
        ----------
        beta : np.ndarray, shape = [n]
            Vector of estimates of fixed effects.
        gamma : np.ndarray, shape = [k]
            Vector of estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters

        Returns
        -------
            hessian: np.ndarray, shape = [k, k]
                Hessian of the loss function with respect to gamma ∇²_𝛄[ℒ](β, 𝛄) + lg*I.
        """

        return super().hessian_gamma(beta, gamma, **kwargs) + self.lg * np.eye(self.problem.num_random_effects)

    def optimal_tgamma(self, tbeta, gamma, **kwargs):
        """
        Returns tgamma which minimizes the loss function with all other variables fixed.

        It is a projection of gamma on the sparse subspace with no more than nnz_gamma elements,
        which can be constructed by taking nnz_gamma largest elements from gamma and setting the rest to be 0.
        In addition, it preserves that for all the elements where tbeta = 0 it implies that tgamma = 0 as well.

        Parameters
        ----------
        tbeta : np.ndarray, shape = [n]
            Vector of (nnz_beta)-sparse estimates for fixed parameters.
        gamma : np.ndarray, shape = [k]
            Vector of covariance estimates of random effects.
        kwargs :
            Not used, left for future and for passing debug/experimental parameters.

        Returns
        -------
        tgamma : np.ndarray, shape = [k]
            Minimizer of the loss function w.r.t tgamma with other arguments fixed.
        """
        tgamma = np.zeros(len(gamma))
        idx = tbeta != 0
        idx_gamma = self.beta_to_gamma_map[idx]
        idx_gamma = (idx_gamma[idx_gamma >= 0]).astype(int)
        tgamma[idx_gamma] = gamma[idx_gamma]
        return self._take_only_k_max(tgamma, self.j)


class LinearLMEOracleW(LinearLMEOracleRegularized):

    def __init__(self, problem: LinearLMEProblem, lb=0.1, lg=0.1, nnz_tbeta=3, nnz_tgamma=3):
        super().__init__(problem, lb, lg, nnz_tbeta, nnz_tgamma)
        self.beta = None
        self.drop_penalties_beta = None
        self.drop_penalties_gamma = None

    def _recalculate_drop_matrices(self, beta, gamma):
        if np.all(self.gamma == gamma) and np.all(self.beta == beta):
            return None
        self._recalculate_cholesky(gamma)

        self.drop_penalties_beta = np.zeros(self.problem.num_fixed_effects)
        self.drop_penalties_gamma = np.zeros(self.problem.num_random_effects)
        for j, ((x, y, z, l), L_inv) in enumerate(zip(self.problem, self.omega_cholesky_inv)):
            # Calculate drop price for gammas individually
            xi = y - x.dot(beta)
            Lxi = L_inv.dot(xi)
            Lx = L_inv.dot(x)
            Lz = L_inv.dot(z)
            h1 = np.sum(Lz ** 2, axis=0)
            g1 = Lz.T.dot(Lxi) ** 2
            self.drop_penalties_gamma += -gamma * g1 / (1 - gamma * h1) + np.log(1 + gamma * h1 / (1 - gamma * h1))
            # Calculate drop price for betas only
            self.drop_penalties_beta += -2 * beta * Lx.T.dot(Lxi)
            self.drop_penalties_beta += -beta ** 2 * np.sum(Lx ** 2, axis=0)
            # Calculate drop price for gammas given dropped betas
            idx_beta = []
            idx_gamma = []
            for i, k in enumerate(self.beta_to_gamma_map):
                if k >= 0:
                    idx_beta.append(i)
                    idx_gamma.append(k)
            idx_beta = np.array(idx_beta)
            idx_gamma = np.array(idx_gamma).astype(int)
            x_s = x[:, idx_beta]
            beta_s = beta[idx_beta]
            gamma_s = gamma[idx_gamma]
            z_s = z[:, idx_gamma]
            Lz_s = L_inv.dot(z_s)
            h1_s = np.sum(Lz_s ** 2, axis=0)
            g2_s = np.sum((Lxi.reshape((len(Lxi), 1)) + L_inv.dot(x_s * beta_s)) * Lz_s, axis=0)
            self.drop_penalties_beta[idx_beta] += (-gamma_s * (g2_s ** 2) / (1 - gamma_s * h1_s)
                                                   + np.log(1 + gamma_s * h1_s / (1 - gamma_s * h1_s)))

        # we invert the sign and take into account the 1/2 multiplier for the loss function
        self.drop_penalties_beta /= -2
        self.drop_penalties_gamma /= -2
        self.beta = beta
        return None

    def loss(self, beta: np.ndarray, gamma: np.ndarray, tbeta: np.ndarray = None, tgamma: np.ndarray = None, **kwargs):
        if self.drop_penalties_beta is None or self.drop_penalties_gamma is None:
            self._recalculate_drop_matrices(beta, gamma)
        return (super(LinearLMEOracleRegularized, self).loss(beta, gamma, **kwargs)
                + self.lb / 2 * sum(self.drop_penalties_beta*(beta - tbeta) ** 2)
                + self.lg / 2 * sum(self.drop_penalties_gamma*(gamma - tgamma) ** 2))

    def optimal_beta(self, gamma: np.ndarray, tbeta: np.ndarray = None, beta: np.ndarray = None, **kwargs):
        if self.drop_penalties_beta is None:
            if beta is not None:
                self._recalculate_drop_matrices(beta, gamma)
            else:
                raise ValueError("Drop penalties for beta are not initialized")

        kernel, tail = super(LinearLMEOracleRegularized, self).optimal_beta(gamma, _dont_solve_wrt_beta=True, **kwargs)
        return np.linalg.solve(self.lb * np.diag(self.drop_penalties_beta) + kernel,
                               self.lb * self.drop_penalties_beta * tbeta + tail)

    def gradient_gamma(self, beta: np.ndarray, gamma: np.ndarray, tgamma: np.ndarray = None, **kwargs) -> np.ndarray:
        if self.drop_penalties_gamma is None:
            self._recalculate_drop_matrices(beta, gamma)
        return (super(LinearLMEOracleRegularized, self).gradient_gamma(beta, gamma, tgamma=tgamma, **kwargs)
                + self.lg * self.drop_penalties_gamma * (gamma - tgamma))

    def hessian_gamma(self, beta: np.ndarray, gamma: np.ndarray, **kwargs) -> np.ndarray:
        if self.drop_penalties_gamma is None:
            self._recalculate_drop_matrices(beta, gamma)
        return super(LinearLMEOracleRegularized, self).hessian_gamma(beta, gamma, **kwargs) + self.lg * np.diag(
            self.drop_penalties_gamma)

    def optimal_tbeta(self, beta: np.ndarray, gamma: np.ndarray = None, **kwargs):
        self._recalculate_drop_matrices(beta, gamma)
        tbeta = np.zeros(len(beta))
        idx_k_max = np.abs(self.drop_penalties_beta*beta).argsort()[-self.k:]
        tbeta[idx_k_max] = beta[idx_k_max]
        return tbeta

    def optimal_tgamma(self, tbeta, gamma, beta: np.ndarray = None, **kwargs):
        self._recalculate_drop_matrices(beta, gamma)
        tgamma = np.zeros(len(gamma))
        idx = tbeta != 0
        idx_gamma = self.beta_to_gamma_map[idx]
        idx_gamma = (idx_gamma[idx_gamma >= 0]).astype(int)
        tgamma[idx_gamma] = gamma[idx_gamma]
        idx_k_max = np.abs(self.drop_penalties_gamma * tgamma).argsort()[-self.j:]
        tgamma2 = np.zeros(len(gamma))
        tgamma2[idx_k_max] = tgamma[idx_k_max]
        return tgamma2
