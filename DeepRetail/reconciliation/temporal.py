from DeepRetail.forecasting.utils import get_numeric_frequency
from DeepRetail.forecasting.statistical import StatisticalForecaster
from DeepRetail.reconciliation.utils import (
    get_factors,
    compute_resampled_frequencies,
    compute_matrix_S,
    resample_temporal_level,
    reverse_order,
    get_w_matrix_structural,
    compute_y_tilde,
    get_w_matrix_mse,
)
import numpy as np
import pandas as pd


class TemporalReconciler(object):
    def __init__(self, bottom_level_freq, factors=None, top_fh=1):
        # Ensure that either factors or bottom_freq is given
        # Raise an error otherwise
        if factors is None and bottom_level_freq is None:
            raise TypeError("Either factors or bottom_freq should be given")

        # Get the numeric frequency
        self.bottom_level_freq = bottom_level_freq
        self.bottom_level_numeric_freq = get_numeric_frequency(self.bottom_level_freq)

        # Construct all factors if they are not given
        if factors is None:
            factors = get_factors(self.bottom_level_numeric_freq)
            self.factors = factors
        else:
            self.factors = factors

        # Initialize extra parameters
        # Build the forecast horizons
        self.fhs = np.flip(factors) * top_fh
        self.frequencies = self.fhs.copy()
        self.m = np.flip(self.frequencies)
        self.max_freq = max(self.frequencies)
        self.total_levels = len(self.factors)

        # Construct the Smat
        self.Smat = compute_matrix_S(self.factors)

    def get_reconciliation_format(self):
        # Converts to the format for reconciliation

        temp_df = self.base_fc_df.copy()

        # Add the temporal indexer to identify temporal levels
        temp_df["temp_indexer"] = (
            temp_df["temporal_level"].astype(str) + "_" + temp_df["fh"].astype(str)
        )

        # Add the model to the unique_id
        temp_df["unique_id_model"] = temp_df["unique_id"] + "-" + temp_df["Model"]

        # Pivot
        temp_df = pd.pivot_table(
            temp_df,
            index="unique_id_model",
            columns="temp_indexer",
            values="y",
            aggfunc="first",
        )

        # Should have another option for when we have cv too.

        # order the columns
        cols = temp_df.columns.tolist()
        # first should be the column with the highest value before the _ and the lowest after the _
        cols.sort(key=lambda x: (int(x.split("_")[0]), int(x.split("_")[1])))
        # reverse the order
        cols = reverse_order(cols, self.frequencies)
        # add the new order
        temp_df = temp_df[cols]

        return temp_df

    def compute_matrix_W(self, reconciliation_method, residual_df=None):
        # Computes the matrix W

        # For structural scalling
        if reconciliation_method == "struc":
            Wmat = get_w_matrix_structural(
                self.frequencies, len(self.reconciliation_ready_df)
            )

        elif reconciliation_method == "mse":
            if residual_df is None:
                raise ValueError("Residuals should be given for mse reconciliation")

            # Get the squared residuals
            residual_df["residual_squarred"] = residual_df["residual"] ** 2

            # Groupby unique_id, temporal_level and fh and get the Mean Squared Error
            residual_df = (
                residual_df.groupby(["unique_id", "temporal_level", "fh"])
                .agg({"residual_squarred": "mean"})
                .reset_index()
            )

            # Get the matrix W
            Wmat = get_w_matrix_mse(residual_df)

        elif reconciliation_method == "variance":
            ...

        else:
            raise ValueError("Reconciliation method not supported")

        return Wmat

    def get_reconciled_predictions(self):
        # function to get the reconciliated predictions for every value on the df

        # First extract values from the dataframe
        values = self.reconciliation_ready_df.values
        ids = self.reconciliation_ready_df.index
        cols = self.reconciliation_ready_df.columns

        # For every set of base forecasts reconcile using the reconciliation function compute_y_tilde
        reconciled_values = [
            compute_y_tilde(y, self.Smat, mat) for y, mat in zip(values, self.Wmat)
        ]

        # Convert to dataframe
        reconcilded_df = pd.DataFrame(reconciled_values, index=ids, columns=cols)

        return reconcilded_df

    def reverse_reconciliation_format(self, reco_method):
        # Function to reverse the reconciliation format to the original one

        temp_df = self.base_fc_df.copy()
        reco_df = self.reconciled_df

        # Prepare the base forecasts
        # Get the temp indexer
        temp_df["temp_indexer"] = (
            temp_df["temporal_level"].astype(str) + "_" + temp_df["fh"].astype(str)
        )

        # Melt the reconciled dataframe
        reco_df = reco_df.reset_index()
        reco_df = pd.melt(
            reco_df,
            id_vars="unique_id_model",
            value_vars=reco_df.columns[1:],
            var_name="temp_indexer",
            value_name="y",
        )

        # Split the unique id and the model
        reco_df["unique_id"] = reco_df["unique_id_model"].apply(
            lambda x: x.split("-")[0]
        )
        reco_df["Base_Model"] = reco_df["unique_id_model"].apply(
            lambda x: x.split("-")[1]
        )

        # Add the Model
        reco_df["Model"] = "TR" + "-" + reco_method + "-" + reco_df["Base_Model"]

        # Drop the unique_id_model and the base model
        reco_df = reco_df.drop(["unique_id_model", "Base_Model"], axis=1)

        # rename the column for base forecasts
        temp_df = temp_df.rename(columns={"y": "y_base"})

        # merge with the base forecasts
        reco_df = reco_df.merge(
            temp_df[["unique_id", "temporal_level", "fh", "temp_indexer", "y_base"]],
            on=["unique_id", "temp_indexer"],
            how="left",
        ).drop("temp_indexer", axis=1)

        return reco_df

    def fit(self, base_fc_df):
        self.base_fc_df = base_fc_df.copy()
        # Converts to the right forecast format
        self.reconciliation_ready_df = self.get_reconciliation_format()

    def reconcile(self, reconciliation_method, residual_df=None):
        # reconciles

        # Get the Weight matrix
        self.Wmat = self.compute_matrix_W(
            reconciliation_method, residual_df=residual_df
        )

        # Reconciles
        self.reconciled_df = self.get_reconciled_predictions()

        # reverses the format
        self.reconciled_df = self.reverse_reconciliation_format(reconciliation_method)

        return self.reconciled_df


class THieF(object):
    def __init__(self, bottom_level_freq, factors=None, top_fh=1):
        # Ensure that either factors or bottom_freq is given
        # Raise an error otherwise
        if factors is None and bottom_level_freq is None:
            raise TypeError("Either factors or bottom_freq should be given")

        # Get the numeric frequency
        self.bottom_level_freq = bottom_level_freq
        self.bottom_level_numeric_freq = get_numeric_frequency(self.bottom_level_freq)

        # Construct all factors if they are not given
        if factors is None:
            factors = get_factors(self.bottom_level_numeric_freq)
            self.factors = factors
        else:
            self.factors = factors

        # Initialize extra parameters
        # Build the forecast horizons
        self.fhs = np.flip(factors) * top_fh
        self.frequencies = self.fhs.copy()
        self.m = np.flip(self.frequencies)
        self.max_freq = max(self.frequencies)
        self.total_levels = len(self.factors)

        # array indices for the flatten base forecasts
        self.level_indices = np.cumsum(np.insert(self.fhs, 0, 0))
        # self.level_indices = np.cumsum(self.fhs)

        # Get the resampled frequencies for upscaling the data
        self.resampled_factors = compute_resampled_frequencies(
            self.factors, self.bottom_level_freq
        )

        # Construct the Smat
        self.Smat = compute_matrix_S(self.factors)

    def fit(self, original_df, holdout=True, cv=None, format="pivoted"):
        # In this method I build the hierarchy
        # I need to see how I will use the holdout and the cv paremeter

        self.original_df = original_df
        self.holdout = holdout

        # If we have holdout:
        if self.holdout:
            # Initialize variables
            self.cv = cv
            end_point = self.bottom_level_numeric_freq + self.cv - 1

            # Initialie lists for train and test
            self.resampled_train_dfs = []
            self.resampled_test_dfs = []

            for z in range(self.cv):
                # Manual cross-validation
                # Define start and end points for each fold
                temp_startpoint = end_point - z
                temp_endpoint = cv - z - 1

                # Split
                temp_test_df = (
                    self.original_df.iloc[:, -temp_startpoint:-temp_endpoint]
                    if temp_endpoint != 0
                    else self.original_df.iloc[:, -temp_startpoint:]
                )
                temp_train_df = self.original_df.iloc[:, :-temp_startpoint]

                # Resample train first
                temp_resampled_train_df = [
                    resample_temporal_level(temp_train_df, i, self.bottom_level_freq, j)
                    for i, j in zip(self.factors, self.resampled_factors)
                ]
                # Convert to dictionary with factors as keys
                self.resampled_dfs = {
                    self.factors[i]: temp_resampled_train_df[i]
                    for i in range(len(self.factors))
                }

                # add to list
                self.resampled_train_dfs.append(self.resampled_dfs)

                # Repeat for test set
                # I also melt to merge right away
                temp_resampled_test_df = [
                    (
                        resample_temporal_level(
                            temp_test_df, i, self.bottom_level_freq, j
                        )
                        .reset_index()
                        .melt(id_vars="unique_id", value_name="y_true", var_name="date")
                    )
                    for i, j in zip(self.factors, self.resampled_factors)
                ]
                # Add the factor as temporal level to each test dataframe
                for i in range(len(self.factors)):
                    temp_resampled_test_df[i]["temporal_level"] = self.factors[i]

                # Concat the list
                self.resampled_test_dfs.append(pd.concat(temp_resampled_test_df))

            # Add the cv to each test set
            for i in range(len(self.resampled_test_dfs)):
                self.resampled_test_dfs[i]["cv"] = i + 1

            # Concat
            self.resampled_test_dfs = pd.concat(self.resampled_test_dfs)

        # If not, generate a single split.
        else:
            # Get the list of the resampled dataframes
            resampled_dfs = [
                resample_temporal_level(self.original_df, i, self.bottom_level_freq, j)
                for i, j in zip(self.factors, self.resampled_factors)
            ]

            # convert it to a dictionary with the factors as keys
            self.resampled_dfs = {
                self.factors[i]: resampled_dfs[i] for i in range(len(self.factors))
            }

    def predict(self, models, to_return=True):
        # generates base forecasts
        # models is str or list dictionary for each factor
        # for example model_example = {1: ['ETS', 'Naive'], 3: 'ETS', 4: 'ARIMA', 6: 'ETS', 12: 'ETS'}

        # Check if we have a model for each level
        if isinstance(models, str):
            # If not, use the same model for all levels
            models = {i: models for i in self.factors}
        # Check if we have enough models
        elif len(models) != len(self.factors):
            raise ValueError(
                "The number of models should be equal to the number of factors"
            )

        # If we have holdout
        if self.holdout:
            # Initialize a list for the base forecasts and residuals
            temp_total_base_forecasts = []
            temp_total_residuals = []

            for z in range(self.cv):
                # Take the temporal hierarchy for the fold
                self.resampled_dfs = self.resampled_train_dfs[z]

                # Initialize a StatisticalForecaster for each factor
                # Currently only supporting StatisticalForecaster
                self.base_forecasters = {
                    factor: StatisticalForecaster(
                        models=models[factor], freq=self.resampled_factors[i]
                    )
                    for i, factor in enumerate(self.factors)
                }

                # Fit
                for factor in self.factors:
                    self.base_forecasters[factor].fit(
                        self.resampled_dfs[factor], format="pivoted"
                    )

                # Generate base forecasts
                temp_base_forecasts = {
                    factor: self.base_forecasters[factor].predict(
                        h=self.frequencies[i], holdout=False
                    )
                    for i, factor in enumerate(self.factors)
                }

                # Concat in a single dataframe
                self.base_forecasts = pd.concat(temp_base_forecasts, axis=0)

                # Reset index and drop column from multi-index
                # also rename the remaining idnex to get the temporal level
                self.base_forecasts = (
                    self.base_forecasts.reset_index()
                    .drop(columns="level_1")
                    .rename(columns={"level_0": "temporal_level"})
                )

                # Get residuals
                # NOTE: change the get_residual to accept as argument the df
                # This way I can have temp dataframes instead of self.resampled_dfs

                temp_residuals = self.get_residuals()

                # Add the cv to the predictions and the cv
                self.base_forecasts["cv"] = z + 1
                temp_residuals["cv"] = z + 1

                # Add to list
                temp_total_base_forecasts.append(self.base_forecasts)
                temp_total_residuals.append(temp_residuals)

            # Concat
            self.base_forecasts = pd.concat(temp_total_base_forecasts)
            self.base_forecast_residuals = pd.concat(temp_total_residuals)

            # Merge with the true
            self.base_forecasts = pd.merge(
                self.base_forecasts,
                self.resampled_test_dfs,
                on=["unique_id", "date", "temporal_level", "cv"],
                how="left",
            )

            # Return the predictions
            if to_return:
                return self.base_forecasts

        # If we dont have holdout
        else:
            # Initiaze a StatisticalForecaster for each factor
            # Currently only supporting StatisticalForecaster
            self.base_forecasters = {
                factor: StatisticalForecaster(
                    models=models[factor], freq=self.resampled_factors[i]
                )
                for i, factor in enumerate(self.factors)
            }

            # Fit the forecasters
            for factor in self.factors:
                self.base_forecasters[factor].fit(
                    self.resampled_dfs[factor], format="pivoted"
                )

            # Generate base forecasts
            temp_base_forecasts = {
                factor: self.base_forecasters[factor].predict(
                    h=self.frequencies[i], holdout=False
                )
                for i, factor in enumerate(self.factors)
            }

            # Concat in a single dataframe
            self.base_forecasts = pd.concat(temp_base_forecasts, axis=0)

            # Reset index and drop column from multi-index
            # Also rename the remaining index to get the temporal level
            self.base_forecasts = (
                self.base_forecasts.reset_index()
                .drop("level_1", axis=1)
                .rename(columns={"level_0": "temporal_level"})
            )

            # Get the residuals here
            self.get_residuals()

        if to_return:
            return self.base_forecasts

    def get_residuals(self):
        # Estimate residuals for all base forecasters
        temp_residuals = {
            factor: self.base_forecasters[factor].calculate_residuals()
            for factor in self.factors
        }

        # concat
        temp_residuals = pd.concat(temp_residuals, axis=0)

        # add to the right format
        temp_residuals = (
            temp_residuals.reset_index()
            .drop("level_1", axis=1)
            .rename(columns={"level_0": "temporal_level"})
        )

        # keep only relevant columns
        to_keep = ["temporal_level", "unique_id", "cv", "fh", "Model", "residual"]

        # Add to the object
        self.base_forecast_residuals = temp_residuals[to_keep]

        return self.base_forecast_residuals

    def reconcile(self, reconciliation_method):
        # Reconciles base predictions
        # Currently only supporting struc

        # Define the TemporalReconciler
        self.temporal_reconciler = TemporalReconciler(
            bottom_level_freq=self.bottom_level_freq, factors=self.factors
        )

        # Fit the reconciler
        self.temporal_reconciler.fit(self.base_forecasts)

        # Reconcile
        self.reconciled_df = self.temporal_reconciler.reconcile(
            reconciliation_method, residual_df=self.base_forecast_residuals
        )

        # Merge with the base forecasts
        return self.reconciled_df
