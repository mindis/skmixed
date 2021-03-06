from skmixed.lme.models import LinearLMESparseModel
from skmixed.lme.problems import LinearLMEProblem

import unittest

import numpy as np
from sklearn.metrics import mean_squared_error, explained_variance_score, accuracy_score

from skmixed.lme.models import LinearLMESparseModel
from skmixed.lme.problems import LinearLMEProblem


class TestLinearLMESparseModel_with_selectiveness(unittest.TestCase):

    def test_solving_sparse_problem(self):
        trials = 10
        problem_parameters = {
            "groups_sizes": [20, 12, 14, 50, 11],
            "features_labels": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
            "random_intercept": True,
            "obs_std": 0.1,
        }

        model_parameters = {
            "lb": 0.01,
            "lg": 0.01,
            "initializer": None,
            "logger_keys": ('converged', 'loss',),
            "tol": 1e-6,
            "n_iter": 1000,
            "tol_inner": 1e-4,
            "n_iter_inner": 1000,
        }

        max_mse = 0.05
        min_explained_variance = 0.9
        fixed_effects_min_accuracy = 0.7
        random_effects_min_accuracy = 0.7

        fea = []
        rea = []

        for i in range(trials):
            np.random.seed(i)
            true_beta = np.random.choice(2, size=11, p=np.array([0.5, 0.5]))
            if sum(true_beta) == 0:
                true_beta[0] = 1
            true_gamma = np.random.choice(2, size=11, p=np.array([0.3, 0.7])) * true_beta

            problem, true_model_parameters = LinearLMEProblem.generate(**problem_parameters,
                                                                       beta=true_beta,
                                                                       gamma=true_gamma,
                                                                       seed=i)
            model = LinearLMESparseModel(**model_parameters,
                                         nnz_tbeta=sum(true_beta),
                                         nnz_tgamma=sum(true_gamma),
                                         regularization_type="loss-weighted"
                                         )
            model2 = LinearLMESparseModel(**model_parameters,
                                          nnz_tbeta=sum(true_beta),
                                          nnz_tgamma=sum(true_gamma),
                                          regularization_type="l2"
                                          )

            x, y = problem.to_x_y()
            model.fit(x, y)
            model2.fit(x, y)

            logger = model.logger_
            loss = np.array(logger.get("loss"))
            self.assertTrue(np.all(loss[1:] - loss[:-1] <= 0),
                            msg="%d) Loss does not decrease monotonically with iterations. (seed=%d)" % (i, i))

            y_pred = model.predict(x)
            explained_variance = explained_variance_score(y, y_pred)
            mse = mean_squared_error(y, y_pred)

            y_pred2 = model2.predict(x)
            explained_variance2 = explained_variance_score(y, y_pred2)
            mse2 = mean_squared_error(y, y_pred2)

            coefficients = model.coef_
            maybe_tbeta = coefficients["tbeta"]
            maybe_tgamma = coefficients["tgamma"]
            fixed_effects_accuracy = accuracy_score(true_beta, maybe_tbeta != 0)
            random_effects_accuracy = accuracy_score(true_gamma, maybe_tgamma != 0)

            coefficients2 = model2.coef_
            maybe_tbeta2 = coefficients2["tbeta"]
            maybe_tgamma2 = coefficients2["tgamma"]
            fixed_effects_accuracy2 = accuracy_score(true_beta, maybe_tbeta2 != 0)
            random_effects_accuracy2 = accuracy_score(true_gamma, maybe_tgamma2 != 0)
            print("\n %d) MSE    EV FEA REA")
            print("%.4f  %.4f %.4f %.4f" % (mse, explained_variance, fixed_effects_accuracy, random_effects_accuracy))
            print("%.4f  %.4f %.4f %.4f" % (mse2, explained_variance2, fixed_effects_accuracy2, random_effects_accuracy2))

            # maybe_per_group_coefficients = coefficients["per_group_coefficients"]

            self.assertGreater(explained_variance, min_explained_variance,
                               msg="%d) Explained variance is too small: %.3f < %.3f. (seed=%d)"
                                   % (i,
                                      explained_variance,
                                      min_explained_variance,
                                      i))
            self.assertGreater(max_mse, mse,
                               msg="%d) MSE is too big: %.3f > %.2f  (seed=%d)"
                                   % (i,
                                      mse,
                                      max_mse,
                                      i))
            self.assertGreater(fixed_effects_accuracy, fixed_effects_min_accuracy,
                               msg="%d) Fixed Effects Selection Accuracy is too small: %.3f < %.2f  (seed=%d)"
                                   % (i,
                                      fixed_effects_accuracy,
                                      fixed_effects_min_accuracy,
                                      i)
                               )
            self.assertGreater(random_effects_accuracy, random_effects_min_accuracy,
                               msg="%d) Random Effects Selection Accuracy is too small: %.3f < %.2f  (seed=%d)"
                                   % (i,
                                      random_effects_accuracy,
                                      random_effects_min_accuracy,
                                      i)
                               )
            fea.append(fixed_effects_accuracy)
            rea.append(random_effects_accuracy)

        return None
