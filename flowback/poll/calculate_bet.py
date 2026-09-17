# Can use CrossHair for formal verification
# crosshair check flowback/poll/calculate_bet.py

import numpy as np

# Small decimal (AT LEAST a magnitude below 10^(-6))
def get_small_decimal(power_of: int):
    """
    post: __return__ <= 1e-07
    """
    if power_of >= -6:
        return 10 ** -7
    return 10**power_of


def previous_outcome_avg_calculate(previous_outcomes: list[float]):
    """
    pre: all(0.0 <= x <= 1.0 for x in previous_outcomes)
    post: 0.0 <= __return__ <= 1.0
    """
    previous_outcome_avg = 0 if len(previous_outcomes) == 0 else sum(previous_outcomes) / len(previous_outcomes)
    return previous_outcome_avg


def no_previous_bets_combined(current_bets_from_ith_user: list[float | None]) -> float | None:
    """
    When no previous bets exist, return average of current bets for a given statement,
    or None if all current bets for that statement are None.

    pre: len(current_bets_from_ith_user) > 0
    pre: all(0 <= bet <= 1 for bet in current_bets_from_ith_user)
    post: __return__ is None or 0.0 <= __return__ <= 1.0
    """
    if all(bets is None for bets in current_bets_from_ith_user):
        return None
    else:
        return sum(current_bets_from_ith_user) / len(current_bets_from_ith_user)


def covariance(arr_1: list[float], arr_2: list[float]) -> float:
    """
    To calculate the covariance you need their mean to be 0 (and ig standard devasion of 1?) This normalization allows one to calculate covariance (and you can calculate correlation from covariance, you probably know roughly what correlation is)
    so it changes every entry in both arrays to the mean of themselves, which is part of this normalization step so one can calculate the covariance (and thus in principle correlation)

    This is ultimately used to calculate how much a predictors previous votes correlate with actual results, which is what we're ultiumately building (a non-monetary prediction market)

    pre: len(arr_1) == len(arr_2)
    pre: len(arr_1) > 0
    post: arr_1 != arr_2 or __return__ >= 0.0
    """
    covariance_array = [(arr_1[i] - np.mean(arr_1)) * (arr_2[i] - np.mean(arr_2)) for i in range(len(arr_1))]
    return sum(covariance_array) / len(arr_1)
