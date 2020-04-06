from typing import Any, Callable, List, Tuple, Optional, Union

import numpy as np
from scipy.integrate import solve_ivp


class SEIR:
    """
    Implementation of a SEIR model
    """
    def __init__(self,
                 *,
                 incubation_period: Union[int, float, np.ndarray],
                 infectious_period: Union[int, float, np.ndarray],
                 initial_R0: Union[int, float],
                 hospitalization_probability: Union[float, np.ndarray],
                 hospitalization_duration: Union[float, np.ndarray],
                 hospitalization_lag_from_onset: Union[float, np.ndarray],
                 icu_probability: Union[float, np.ndarray],
                 icu_duration: Union[float, np.ndarray],
                 icu_lag_from_onset: Union[float, np.ndarray],
                 death_probability: Union[float, np.ndarray],
                 death_lag_from_onset: Union[float, np.ndarray],
                 population: Union[float, np.ndarray],
                 compartments: Optional[List[Any]] = None,
                 contacts_matrix: Optional[np.ndarray] = None,
                 restrictions_function: Optional[
                     Callable[[float], Union[float, np.ndarray]]] = None,
                 imported_cases_function: Optional[Callable] = None):
        """
        Initializes the SEIR models parameters and computes the infectivity
        rate from the contacts matrix, R0, and infective_duration. Supports
        compartmentalizing the population to, e.g., age-groups.

        Keyword arguments:
        incubation_period: Union[int, float, np.ndarray]
            Incubation period of the disease in days. If an array,
            it should be the incubation period for each population compartment.
        infectious_period: Union[int, float, np.ndarray]
            How long a patient can infect others (in days). If an array,
            it should be the infectious period for each population compartment.
        initial_R0: Union[int, float]
            Basic reproductive number of the disease
        hospitalization_probability: Union[float, np.ndarray]
            Probability that an infected person needs hospitalization.
            If an array, it should be the hospitalization probability
            for each population compartment.
        hospitalization_duration: Union[float, np.ndarray]
            Average duration of a hospitalization in days. If an array,
            it should be the average hospitalization durations for each
            population compartment.
        hospitalization_lag_from_onset: Union[float, np.ndarray]
            Average time from the onset of symptoms to admission to hospital.
            If an array, it should be the average time to hospitalization for
            each population compartment.
        icu_probability: Union[float, np.ndarray]
            Probability that an infected person needs hospitalization.
            If an array, it should be the probability for each population
            compartment.
        icu_duration: Union[float, np.ndarray]
            Average duration of the need for intensive care in days.
            If an array, it should be the average durations for each population
            compartment.
        icu_lag_from_onset: Union[float, np.ndarray]
            Average time from the onset of symptoms to admission to ICU.
            If an array, it should be the average time to intensive care for
            each population compartment.
        death_probability: Union[float, np.ndarray]
            Probability that an infected person dies from the disease.
            If an array, it should be the probability for each population
            compartment.
        death_lag_from_onset: Union[float, np.ndarray]
            Average time from the onset of symptoms to death
            If an array, it should be the average time to death for
            each population compartment.
        population: Union[int, float, np.ndarray]
            The total population. If an array, it should be the number of
            people in each population compartment.
        compartments: Optional[List[Any]]
            A description of each compartment of the population.
            For age-compartmentalized population this could be a list of
            the age for each compartment, e.g.,
            [ (0, 5), (5,10), (10,40), (40, 150), (150, 'inf') ]
        contacts_matrix: Optional[np.ndarray]
            A matrix C[i,j] describing the daily number of contacts a person of
            compartment 'i' has with the population of compartment 'j'.
        restrictions_function: Optional[Callable[[float],
                                        Union[float, np.ndarray]]]
            A function with signature `fun(time)` that outputs a matrix of
            the same shape as `contacts_matrix` or a float. At each
            timestep the `restrictions_function` is used to augment
            the infectivity rate matrix by a Hadamard product
            from the function's output.
        imported_cases_function: Optional[Callable] = None):
        """
        # Set a single age group if nothing was provided
        if compartments:
            self.compartments = compartments
        else:
            self.compartments = ['All']

        self.num_compartments = len(self.compartments)

        # Save arguments inside the instance
        self.incubation_period = self._fix_size(incubation_period)
        self.infectious_period = self._fix_size(infectious_period)
        self.initial_R0 = initial_R0
        self.hospitalization_probability = self._fix_size(
            hospitalization_probability)
        self.hospitalization_duration = hospitalization_duration
        self.hospitalization_lag_from_onset = hospitalization_lag_from_onset
        self.icu_probability = self._fix_size(icu_probability)
        self.icu_duration = icu_duration
        self.icu_lag_from_onset = icu_lag_from_onset
        self.death_probability = self._fix_size(death_probability)
        self.death_lag_from_onset = death_lag_from_onset
        if isinstance(population, (int, float)):
            assert self.num_compartments == 1
        elif isinstance(population, np.ndarray):
            assert population.size == self.num_compartments
        self.population = self._fix_size(population)

        if contacts_matrix:
            assert contacts_matrix.shape[0] == len(self.compartments)
            assert contacts_matrix.shape[1] == len(self.compartments)
        else:
            contacts_matrix = np.ones(
                (self.num_compartments, self.num_compartments))

        self.infectivity_matrix = self._compute_infectivity_matrix(
            contacts_matrix)

        self.restrictions_function = restrictions_function
        self.imported_cases_function = imported_cases_function

        self.Y0: Optional[np.ndarray] = None
        self.SEIR_solution = None

    def _compute_infectivity_matrix(self,
                                    contacts_matrix: np.ndarray) -> np.ndarray:

        normalization = 1 / self.infectious_period * self.initial_R0 * self.population.sum(
        ) / (self.population @ contacts_matrix).sum()
        return normalization * contacts_matrix

    def _fix_size(self, x: Union[np.ndarray, float, int]) -> np.ndarray:
        """
        Fixes the size of the input to have
        the same size as there are age groups
        """
        if isinstance(x, (int, float)):
            return np.ones(self.num_compartments) * x
        else:
            assert x.size == self.num_compartments
            return x

    def __call__(self, t, Y):
        """
        Computes dY/dt of the SEIR model.
        """
        if self.restrictions_function:
            infectivity_matrix = np.multiply(restrictions_function(t),
                                             self.infectivity_matrix)
        else:
            infectivity_matrix = self.infectivity_matrix

        Sa, Ea, Ia, Ra = np.split(Y, 4)

        dS_dt = -np.divide(Sa, self.population) * (infectivity_matrix @ Ia)
        dE_dt = -dS_dt - np.divide(Ea, self.incubation_period)
        dI_dt = np.divide(Ea, self.incubation_period) - np.divide(
            Ia, self.infectious_period)
        dR_dt = np.divide(Ia, self.infectious_period)

        if self.imported_cases_function:
            DS, DE, DI = self.imported_cases_function(t)
            dS_dt += DS
            dE_dt += DE
            dI_dt += DI
        return np.concatenate([dS_dt, dE_dt, dI_dt, dR_dt])

    def set_initial_state(
            self,
            population_susceptible: Union[int, float, np.ndarray],
            population_exposed: Union[int, float, np.ndarray],
            population_infected: Union[int, float, np.ndarray],
            probabilities: bool = False):

        if probabilities:
            S = np.multiply(population_susceptible, self.population)
            E = np.multiply(population_exposed, self.population)
            I = np.multiply(population_infected, self.population)
        else:
            if isinstance(population_susceptible, (int, float)):
                S = self._fix_sizes(
                    population_susceptible) / self.num_compartments
            elif isinstance(population_susceptible, np.ndarray):
                assert population_susceptible.size == self.num_compartments
                S = population_susceptible

            if isinstance(population_exposed, (int, float)):
                E = self._fix_sizes(population_exposed) / self.num_compartments
            elif isinstance(population_exposed, np.ndarray):
                assert population_exposed.size == self.num_compartments
                E = population_exposed

            if isinstance(population_infected, (int, float)):
                I = self._fix_sizes(population_infected) / self.num_compartments
            elif isinstance(population_infected, np.ndarray):
                assert population_infected.size == self.num_compartments
                I = population_infected

        R = np.zeros(self.num_compartments)

        self.Y0 = np.concatenate([S, E, I, R])

    def simulate(self, days_to_simulate: Union[int, float]):

        solution = solve_ivp(fun=self,
                             t_span=[0, days_to_simulate],
                             y0=self.Y0,
                             dense_output=True,
                             max_step=0.5,
                             method='DOP853')

        def SEIR_solution(time: np.ndarray):
            postime_mask = time >= 0

            SEIR = np.swapaxes(solution.sol(time[postime_mask]), 0, 1)
            INI = np.repeat(np.expand_dims(self.Y0, 0),
                            time.size - np.count_nonzero(postime_mask),
                            axis=0)
            return np.concatenate([INI, SEIR])

        self.SEIR_solution = SEIR_solution

    def evaluate_solution(self, time):
        # Evaluate SEIR model results
        SEIR = self.SEIR_solution(time)
        S, E, I, R = np.split(SEIR, 4, axis=-1)

        # Compute the cumulative sum of infected people
        I_new_cases_a_day = np.divide(E, self.incubation_period)
        Icumulative = np.cumsum(I_new_cases_a_day, axis=0)

        # Compute the number of hospitalized people for each day
        Shl, Ehl, Ihl, Rhl = np.split(
            self.SEIR_solution(time - self.hospitalization_lag_from_onset),
            4,
            axis=-1)
        H_new_cases_a_day = np.multiply(self.hospitalization_probability,
                                        np.divide(Ehl, self.incubation_period))
        Hwindow = np.ones(self.hospitalization_duration)
        H_active_cases = np.stack([
            np.convolve(H_new_cases_a_day[:, i], Hwindow, mode='same')
            for i in range(self.num_compartments)
        ],
                                  axis=-1)

        # Compute the number of people in ICU for each day
        SEIR_icu_lag = self.SEIR_solution(time - self.icu_lag_from_onset)
        E_icu_lag = np.split(SEIR_icu_lag, 4, axis=-1)[2]
        ICU_new_cases_a_day = np.multiply(
            self.icu_probability, np.divide(E_icu_lag, self.incubation_period))
        ICUwindow = np.ones(self.icu_duration)
        ICU_active_cases = np.stack([
            np.convolve(ICU_new_cases_a_day[:, i], Hwindow, mode='same')
            for i in range(self.num_compartments)
        ],
                                    axis=-1)

        # Compute the total number of deaths
        SEIR_death_lag = self.SEIR_solution(time - self.death_lag_from_onset)
        E_death_lag = np.split(SEIR_death_lag, 4, axis=-1)[1]
        DEATH_new_cases_a_day = np.multiply(
            self.death_probability,
            np.divide(E_death_lag, self.incubation_period))
        deaths = np.cumsum(DEATH_new_cases_a_day, axis=0)
        return S, E, I, R, H_active_cases, ICU_active_cases, deaths


if __name__ == '__main__':

    model = SEIR(incubation_period=3,
                 infectious_period=7,
                 initial_R0=2.3,
                 hospitalization_probability=0.01,
                 hospitalization_duration=21,
                 hospitalization_lag_from_onset=6,
                 icu_probability=0.001,
                 icu_duration=7,
                 icu_lag_from_onset=21,
                 death_probability=0.1,
                 death_lag_from_onset=27,
                 compartments=[(1, 5), (5, 10)],
                 population=np.array([2.5e6, 1e6]))

    model.set_initial_state(population_susceptible=0.99,
                            population_exposed=0.005,
                            population_infected=0.005,
                            probabilities=True)

    model.simulate(200)

    time = np.arange(0, 200, 1, dtype=int)
    S, E, I, R, H_active_cases, ICU_active_cases, deaths = model.evaluate_solution(time)

    import matplotlib.pyplot as plt
    plt.plot(time, I)
    plt.show()
