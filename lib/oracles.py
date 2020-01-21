import numpy as np

from lib.problems import LinearLMEProblem


class LinearLMEOracle:
    def __init__(self, problem: LinearLMEProblem, mode='fast'):
        self.problem = problem
        assert mode == 'naive' or mode == 'fast', "Unknown mode: %s" % mode
        self.mode = mode
        if self.mode == 'fast':
            self.omegas_inv = []
            self.zTomegas_inv = []
            self.zTomegas_invZ = []
            self.xTomegas_invY = []
            self.xTomegas_invX = []
            self.old_gamma = None

    def recalculate_inverse_matrices(self, gamma: np.ndarray) -> None:
        if (self.old_gamma == gamma).all():
            return None
        if self.old_gamma is None:
            self.omegas_inv = []
            self.zTomegas_inv = []
            self.zTomegas_invZ = []
            self.xTomegas_invY = []
            self.xTomegas_invX = []
            for x, y, z, l in self.problem:
                omega_inv = np.linalg.inv(z.dot(np.diag(gamma)).dot(z.T) + l)
                zTomega = z.T.dot(omega_inv)
                zTomegaZ = zTomega.dot(z)
                self.omegas_inv.append(omega_inv)
                self.zTomegas_inv.append(zTomega)
                self.zTomegas_invZ.append(zTomegaZ)
                xTomega_inv = x.T.dot(omega_inv)
                self.xTomegas_invX.append(xTomega_inv.dot(x))
                self.xTomegas_invY.append(xTomega_inv.dot(y))
            self.old_gamma = gamma
        else:
            if (self.old_gamma - gamma == 0).any():
                self.old_gamma = None
                self.recalculate_inverse_matrices(gamma)
            else:
                dGamma_inv = np.diag(1 / (self.old_gamma - gamma))
                for i, (x, y, z, l) in enumerate(self.problem):
                    kernel_update = np.linalg.inv(dGamma_inv - self.zTomegas_invZ[i])
                    new_omega = self.omegas_inv[i] + self.omegas_inv[i].dot(z).dot(kernel_update).dot(
                        self.zTomegas_inv[i])
                    new_zTomega = z.T.dot(new_omega)
                    new_zTomegaZ = new_zTomega.dot(z)
                    self.omegas_inv[i] = new_omega
                    self.zTomegas_inv[i] = new_zTomega
                    self.zTomegas_invZ[i] = new_zTomegaZ
                    xTomega_inv = x.T.dot(new_omega)
                    self.xTomegas_invY[i] = xTomega_inv.dot(y)
                    self.xTomegas_invX[i] = xTomega_inv.dot(x)
                self.old_gamma = gamma

    def loss(self, beta: np.ndarray, gamma: np.ndarray) -> float:
        gamma_mat = np.diag(gamma)
        result = 0
        problem = self.problem
        if self.mode == 'naive':
            for x, y, z, l in problem:
                omega = z.dot(gamma_mat).dot(z.T) + l
                xi = y - x.dot(beta)
                sign, determinant = np.linalg.slogdet(omega)
                result += 1 / 2 * xi.T.dot(np.linalg.inv(omega)).dot(xi) + 1 / 2 * sign * determinant
        elif self.mode == 'fast':
            self.recalculate_inverse_matrices(gamma)
            for i, (x, y, z, l) in enumerate(problem):
                omega_inv = self.omegas_inv[i]
                xi = y - x.dot(beta)
                sign, determinant = np.linalg.slogdet(omega_inv)
                # Minus because we need the det of omega but use the det of its inverse
                result += 1 / 2 * xi.T.dot(omega_inv).dot(xi) - 1 / 2 * sign * determinant
        else:
            raise Exception("Unknown mode: %s" % self.mode)
        return result

    def grad_loss_gamma(self, beta: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        if self.mode == 'naive':
            gamma_mat = np.diag(gamma)
            grad_gamma = np.zeros(len(gamma))
            for j in range(len(gamma)):
                result = 0
                for x, y, z, l in self.problem:
                    omega_inv = z.dot(gamma_mat).dot(z.T) + l
                    xi = y - x.dot(beta)
                    z_col = z[:, j]
                    data_part = z_col.T.dot(np.linalg.inv(omega_inv)).dot(xi)
                    data_part = -1 / 2 * data_part ** 2
                    det_part = 1 / 2 * z_col.T.dot(np.linalg.inv(omega_inv)).dot(z_col)
                    result += data_part + det_part
                grad_gamma[j] = result
            return grad_gamma
        elif self.mode == 'fast':
            if (self.old_gamma == gamma).all():
                result = np.zeros(self.problem.num_random_effects)
                for i, (x, y, z, l) in enumerate(self.problem):
                    xi = y - x.dot(beta)
                    result += 1 / 2 * (np.diag(self.zTomegas_invZ[i]) - self.zTomegas_inv[i].dot(xi) ** 2)
                self.old_gamma = gamma
                return result
            else:
                self.recalculate_inverse_matrices(gamma)
                result = np.zeros(self.problem.num_random_effects)
                for i, (x, y, z, l) in enumerate(self.problem):
                    new_zTomega = self.zTomegas_inv[i]
                    new_zTomegaZ = self.zTomegas_invZ[i]
                    xi = y - x.dot(beta)
                    result += 1 / 2 * (np.diag(new_zTomegaZ) - new_zTomega.dot(xi) ** 2)
                return result

    def hessian_gamma(self, beta: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        if self.mode == 'naive':
            raise NotImplementedError(
                "Hessians are not implemented for the naive mode (it takes forever to compute them)")
        elif self.mode == 'fast':
            result = np.zeros((self.problem.num_random_effects, self.problem.num_random_effects))
            self.recalculate_inverse_matrices(gamma)
            for i, (x, y, z, l) in enumerate(self.problem):
                xi = y - x.dot(beta)
                eta = self.zTomegas_inv[i].dot(xi)
                eta = eta.reshape(len(eta), 1)
                result -= self.zTomegas_invZ[i] ** 2
                result += 2 * eta.dot(eta.T) * self.zTomegas_invZ[i]
            return 1 / 2 * result
        else:
            raise Exception("Unknown mode: %s" % self.mode)

    def optimal_beta(self, gamma: np.ndarray): #, force_naive=False):
        omega = 0
        tail = 0
        if self.mode == 'naive':
            gamma_mat = np.diag(gamma)
            for x, y, z, l in self.problem:
                omega_i = z.dot(gamma_mat).dot(z.T) + l
                omega += x.T.dot(np.linalg.inv(omega_i)).dot(x)
                tail += x.T.dot(np.linalg.inv(omega_i)).dot(y)
        elif self.mode == 'fast':
            if not (self.old_gamma == gamma).all():
                self.recalculate_inverse_matrices(gamma)
            omega = np.sum(self.xTomegas_invX, axis=0)
            tail = np.sum(self.xTomegas_invY, axis=0)
        else:
            raise Exception("Unexpected mode: %s" % self.mode)
        return np.linalg.inv(omega).dot(tail)

    def optimal_random_effects(self, beta, gamma):
        random_effects = []
        for x, y, z, l in self.problem:
            # TODO: Figure out the situation when gamma_i = 0
            inv_g = np.diag(np.array([0 if g == 0 else 1 / g for g in gamma]))
            u = np.linalg.inv(inv_g + z.T.dot(np.linalg.inv(l)).dot(z)).dot(z.T.dot(np.linalg.inv(l)).dot(y - x.dot(beta)))
            random_effects.append(u)
        return np.array(random_effects)

    def predict(self, beta, gamma):
        us = self.optimal_random_effects(beta, gamma)
        answers = []
        for i, (x, _, z, l) in enumerate(self.problem):
            y = x.dot(beta) + z.dot(us[i])
            answers.append(y)
        return answers


class LinearLMEOracleRegularized(LinearLMEOracle):
    def __init__(self, problem: LinearLMEProblem, mode='fast', lb=0.1, lg1=0.1, lg2=0.1):
        super().__init__(problem, mode)
        self.lb=0.1

    #def optimal_beta_reg(self, gamma, tbeta):