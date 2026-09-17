from unittest import TestCase

import numpy as np

from flowback.poll.tasks import quadratic_programming_solver


class TestQuadraticProgrammingSolver(TestCase):
    def assert_solver_result(
        self,
        covariance_matrix: np.ndarray,
        expected_solution: np.ndarray,
        expected_optimal_value: float,
    ) -> None:
        solution, optimal_value, _ = quadratic_programming_solver(covariance_matrix)

        np.testing.assert_allclose(solution, expected_solution, rtol=1e-7, atol=1e-8)
        np.testing.assert_allclose(
            optimal_value,
            expected_optimal_value,
            rtol=1e-7,
            atol=1e-8,
        )

    def test_equally_weights_two_predictors_with_zero_covariance(self):
        self.assert_solver_result(
            covariance_matrix=np.zeros((2, 2)),
            expected_solution=np.array([0.5, 0.5]),
            expected_optimal_value=0.0,
        )

    def test_equally_weights_three_predictors_with_zero_covariance(self):
        self.assert_solver_result(
            covariance_matrix=np.zeros((3, 3)),
            expected_solution=np.array([0.33333333, 0.33333333, 0.33333333]),
            expected_optimal_value=0.0,
        )

    def test_excludes_predictor_with_nonzero_variance(self):
        self.assert_solver_result(
            covariance_matrix=np.diag([0.0, 0.0, 1.0]),
            expected_solution=np.array(
                [0.5, 0.5, 1.87483202e-25],
            ),
            expected_optimal_value=3.514995119900657e-50,
        )

    def test_covariance_matrix_entry_above_one_is_rejected(self):
        with self.assertRaises(ValueError):
            quadratic_programming_solver(np.array([[1.0, 2.0], [2.0, 1.0]]))

    def test_nan_covariance_matrix_returns_unavailable_outputs(self):
        for predictor_count in (2, 3):
            with self.subTest(predictor_count=predictor_count):
                covariance_matrix = np.eye(predictor_count)
                covariance_matrix[0, 1] = covariance_matrix[1, 0] = np.nan
                self.assertEqual(
                    quadratic_programming_solver(covariance_matrix),
                    [None, None, None],
                )
