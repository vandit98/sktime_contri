"""Columnwise transformer."""
# copyright: sktime developers, BSD-3-Clause License (see LICENSE file)

__author__ = ["fkiraly", "mloning"]

__all__ = ["ColumnEnsembleTransformer", "ColumnwiseTransformer"]

import pandas as pd

from sktime.base._meta import _ColumnEstimator, _HeterogenousMetaEstimator
from sktime.transformations.base import BaseTransformer
from sktime.utils.multiindex import rename_multiindex
from sktime.utils.validation.series import check_series

# mtypes that are native pandas
# ColumnEnsembleTransformer uses these internally, since we need (pandas) columns
PANDAS_MTYPES = ["pd.DataFrame", "pd-multiindex", "pd_multiindex_hier"]


class ColumnEnsembleTransformer(
    _HeterogenousMetaEstimator, _ColumnEstimator, BaseTransformer
):
    """Column-wise application of transformers.

    Applies transformations to columns of an array or pandas DataFrame. Simply
    takes the column transformer from sklearn
    and adds capability to handle pandas dataframe.

    This estimator allows different columns or column subsets of the input
    to be transformed separately and the features generated by each transformer
    will be concatenated to form a single feature space.
    This is useful for heterogeneous or columnar data, to combine several
    feature extraction mechanisms or transformations into a single transformer.

    Note: this estimator has the same effect as combining
    ``FeatureUnion`` with ``ColumnSelect``, but can be more convenient or compact.

    Parameters
    ----------
    transformers : sktime trafo, or list of tuples (str, estimator, int or pd.index)
        if tuples, with name = str, estimator is transformer, index as int or index
        if last element is index, it must be int, str, or pd.Index coercible
        if last element is int x, and is not in columns, is interpreted as x-th column
        all columns must be present in an index

        If transformer, clones of transformer are applied to all columns.
        If list of tuples, transformer in tuple is applied to column with int/str index

    remainder : {"drop", "passthrough"} or estimator, default "drop"
        By default, only the specified columns in `transformations` are
        transformed and combined in the output, and the non-specified
        columns are dropped. (default of ``"drop"``).
        By specifying ``remainder="passthrough"``, all remaining columns that
        were not specified in `transformations` will be automatically passed
        through. This subset of columns is concatenated with the output of
        the transformations.
        By setting ``remainder`` to be an estimator, the remaining
        non-specified columns will use the ``remainder`` estimator. The
        estimator must support `fit` and `transform`.

    feature_names_out : str, one of "auto" (default), "flat", "multiindex", "original"
        determines how return columns of return DataFrame-s are named
        has no effect if return mtype is one without column names
        "flat": columns are flat, e.g., "transformername__variablename"
        "multiindex": columns are MultiIndex, e.g., (transformername, variablename)
        "original: columns are as produced by transformers, e.g., variablename
            if this results in non-unique index, ValueError exception is raised
        "auto": as "original" for any unique columns under "original",
            column names as "flat" otherwise

    Attributes
    ----------
    transformers_ : list
        The collection of fitted transformations as tuples of
        (name, fitted_transformer, column). `fitted_transformer` can be an
        estimator, "drop", or "passthrough". In case there were no columns
        selected, this will be the unfitted transformer.
        If there are remaining columns, the final element is a tuple of the
        form:
        ("remainder", transformer, remaining_columns) corresponding to the
        ``remainder`` parameter. If there are remaining columns, then
        ``len(transformers_)==len(transformations)+1``, otherwise
        ``len(transformers_)==len(transformations)``.

    Examples
    --------
    .. Doctest::

        >>> import pandas as pd
        >>> from sktime.transformations.compose import ColumnEnsembleTransformer
        >>> from sktime.transformations.series.detrend import Detrender
        >>> from sktime.transformations.series.difference import Differencer
        >>> from sktime.datasets import load_longley

    Using integers (column iloc references) for indexing:

    .. Doctest::

        >>> y = load_longley()[1][["GNP", "UNEMP"]]
        >>> transformer = ColumnEnsembleTransformer([("difference", Differencer(), 1),
        ...                                 ("trend", Detrender(), 0),
        ...                                 ])
        >>> y_transformed = transformer.fit_transform(y)

    Using strings for indexing:

    >>> df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    >>> transformer = ColumnEnsembleTransformer(
    ...     [("foo", Differencer(), "a"), ("bar", Detrender(), "b")]
    ... )
    >>> transformed_df = transformer.fit_transform(df)

    Applying one transformer to multiple columns, multivariate:

    >>> df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})
    >>> transformer = ColumnEnsembleTransformer(
    ...    [("ab", Differencer(), ["a", 1]), ("c", Detrender(), 2)]
    ... )
    >>> transformed_df = transformer.fit_transform(df)
    """

    _tags = {
        "authors": ["fkiraly", "mloning"],
        "X_inner_mtype": PANDAS_MTYPES,
        "y_inner_mtype": PANDAS_MTYPES,
        "fit_is_empty": False,
        "capability:unequal_length": True,
        "handles-missing-data": True,
    }

    # for default get_params/set_params from _HeterogenousMetaEstimator
    # _steps_attr points to the attribute of self
    # which contains the heterogeneous set of estimators
    # this must be an iterable of (name: str, estimator, ...) tuples for the default
    _steps_attr = "transformers"
    # if the estimator is fittable, _HeterogenousMetaEstimator also
    # provides an override for get_fitted_params for params from the fitted estimators
    # the fitted estimators should be in a different attribute, _steps_fitted_attr
    # this must be an iterable of (name: str, estimator, ...) tuples for the default
    _steps_fitted_attr = "transformers_"

    def __init__(self, transformers, remainder=None, feature_names_out="auto"):
        self.transformers = transformers
        self.remainder = remainder
        self.feature_names_out = feature_names_out
        super().__init__()

        # check remainder argument
        if remainder not in ["drop", "passthrough", None]:
            if not isinstance(remainder, BaseTransformer):
                raise ValueError(
                    "the remainder parameter of ColumnEnsembleTransformer "
                    ' must be one of the strings "drop", "passthrough", None,'
                    "or an sktime transformer inheriting from BaseTransformer"
                )

        # set requires-fh-in-fit depending on transformers
        if isinstance(transformers, BaseTransformer):
            tags_to_clone = [
                "fit_is_empty",
                "requires_X",
                "requires_y",
                "X-y-must-have-same-index",
                "transform-returns-same-time-index",
                "capability:unequal_length",
                "capability:unequal_length:removes",
                "handles-missing-data",
                "capability:missing_values:removes",
                "scitype:transform-output",
                "scitype:transform-labels",
            ]
            self.clone_tags(transformers, tags_to_clone)
        else:
            l_transformers = [(x[0], x[1]) for x in transformers]
            # self._anytagis_then_set("fit_is_empty", False, True, l_transformers)
            self._anytagis_then_set("requires_X", True, False, l_transformers)
            self._anytagis_then_set("requires_y", True, False, l_transformers)
            self._anytagis_then_set(
                "X-y-must-have-same-index", True, False, l_transformers
            )
            self._anytagis_then_set(
                "transform-returns-same-time-index", False, True, l_transformers
            )
            self._anytagis_then_set(
                "capability:unequal_length", False, True, l_transformers
            )
            self._anytagis_then_set(
                "capability:unequal_length:removes", False, True, l_transformers
            )
            self._anytagis_then_set("handles-missing-data", False, True, l_transformers)
            self._anytagis_then_set(
                "capability:missing_values:removes", False, True, l_transformers
            )

            # must be all the same, currently not checking
            tags_to_clone = ["scitype:transform-output", "scitype:transform-labels"]
            self.clone_tags(transformers[0][1], tags_to_clone)

    @property
    def _transformers(self):
        """Make internal list of transformers.

        The list only contains the name and transformers, dropping the columns. This is
        for the implementation of get_params via _HeterogenousMetaEstimator._get_params
        which expects lists of tuples of len 2.
        """
        transformers = self.transformers
        if isinstance(transformers, BaseTransformer):
            return [("transformers", transformers)]
        else:
            return [(name, transformer) for name, transformer, _ in self.transformers]

    @_transformers.setter
    def _transformers(self, value):
        if len(value) == 1 and isinstance(value, BaseTransformer):
            self.transformers = value
        elif len(value) == 1 and isinstance(value, list):
            self.transformers = value[0][1]
        else:
            self.transformers = [
                (name, transformer, columns)
                for ((name, transformer), (_, _, columns)) in zip(
                    value, self.transformers
                )
            ]

    def _check_transformers(self, X):
        transformers = self.transformers

        if isinstance(transformers, BaseTransformer):
            for col in X.columns:
                transformers = [(str(col), transformers, pd.Index([col]))]

        coerced_trafo = []
        indices = []
        for name, transformer, index in transformers:
            c_index = self._coerce_to_pd_index(index, X)
            indices += [c_index]
            coerced_trafo += [(name, transformer, c_index)]
        transformers = coerced_trafo

        # handle remainder
        remainder = self.remainder

        # in the None / "drop" case, we are already done
        if remainder != "passthrough" and not isinstance(remainder, BaseTransformer):
            return transformers

        # if remainder == "passthrough" or isinstance(remainder, BaseTransformer)
        if isinstance(remainder, BaseTransformer):
            rem_t = self.remainder.clone()
        elif remainder == "passthrough":
            from sktime.transformations.compose import Id

            rem_t = Id()

        remain_idx = set()
        for idx in indices:
            remain_idx = remain_idx.union(set(idx))
        remain_idx = set(X.columns).difference(remain_idx)
        remain_idx = self._coerce_to_pd_index(remain_idx, X)

        transformers.append(("remainder", rem_t, remain_idx))

        return transformers

    def _fit(self, X, y=None):
        """Fit transformer to X and y.

        private _fit containing the core logic, called from fit

        Parameters
        ----------
        X : Series or Panel of mtype X_inner_mtype
            if X_inner_mtype is list, _fit must support all types in it
            Data to fit transform to
        y : Series or Panel of mtype y_inner_mtype, default=None
            Additional data, e.g., labels for transformation

        Returns
        -------
        self: reference to self
        """
        transformers = self._check_transformers(X)

        self.transformers_ = []
        self._Xcolumns = list(X.columns)

        for name, transformer, index in transformers:
            transformer_ = transformer.clone()

            transformer_.fit(X.loc[:, index], y)
            self.transformers_.append((name, transformer_, index))

        return self

    def _transform(self, X, y=None):
        """Transform X and return a transformed version.

        private _transform containing core logic, called from transform

        Parameters
        ----------
        X : Series or Panel of mtype X_inner_mtype
            if X_inner_mtype is list, _transform must support all types in it
            Data to be transformed
        y : Series or Panel of mtype y_inner_mtype, default=None
            Additional data, e.g., labels for transformation

        Returns
        -------
        transformed version of X
        """
        Xts = []
        keys = []
        for name, est, index in getattr(self, self._steps_fitted_attr):
            Xts += [est.transform(X.loc[:, index], y)]
            keys += [name]

        Xt = pd.concat(Xts, axis=1, keys=keys)

        # set output column names according to feature_names_out param
        feature_names_out = self.feature_names_out
        msg = f"resulting column index in {self.__class__.__name__}"
        Xt.columns = rename_multiindex(
            Xt.columns, feature_names_out=feature_names_out, idx_name=msg
        )

        return Xt

    @classmethod
    def get_test_params(cls):
        """Return testing parameter settings for the estimator.

        Returns
        -------
        params : dict or list of dict, default = {}
            Parameters to create testing instances of the class
            Each dict are parameters to construct an "interesting" test instance, i.e.,
            `MyClass(**params)` or `MyClass(**params[i])` creates a valid test instance.
            `create_test_instance` uses the first (or only) dictionary in `params`
        """
        from sktime.transformations.series.boxcox import BoxCoxTransformer
        from sktime.transformations.series.exponent import ExponentTransformer

        TRANSFORMERS = [
            ("transformer1", ExponentTransformer()),
            ("transformer2", BoxCoxTransformer()),
        ]

        params1 = {
            "transformers": [(name, estimator, [0]) for name, estimator in TRANSFORMERS]
        }

        params2 = {
            "transformers": [("transformer1", ExponentTransformer(), [0])],
            "remainder": BoxCoxTransformer(method="fixed"),
        }

        params3 = {
            "transformers": [("transformer1", BoxCoxTransformer(), [0])],
            "remainder": "passthrough",
        }

        return [params1, params2, params3]


class ColumnwiseTransformer(BaseTransformer):
    """Apply a transformer columnwise to multivariate series.

    Overview: input multivariate time series and the transformer passed
    in `transformer` parameter is applied to specified `columns`, each
    column is handled as a univariate series. The resulting transformed
    data has the same shape as input data.

    Parameters
    ----------
    transformer : Estimator
        scikit-learn-like or sktime-like transformer to fit and apply to series.
    columns : list of str or None
            Names of columns that are supposed to be transformed.
            If None, all columns are transformed.

    Attributes
    ----------
    transformers_ : dict of {str : transformer}
        Maps columns to transformers.
    columns_ : list of str
        Names of columns that are supposed to be transformed.

    See Also
    --------
    OptionalPassthrough

    Examples
    --------
    >>> from sktime.datasets import load_longley
    >>> from sktime.transformations.series.detrend import Detrender
    >>> from sktime.transformations.compose import ColumnwiseTransformer
    >>> _, X = load_longley()
    >>> transformer = ColumnwiseTransformer(Detrender())
    >>> Xt = transformer.fit_transform(X)
    """

    _tags = {
        "scitype:transform-input": "Series",
        # what is the scitype of X: Series, or Panel
        "scitype:transform-output": "Series",
        # what scitype is returned: Primitives, Series, Panel
        "scitype:instancewise": True,  # is this an instance-wise transform?
        "X_inner_mtype": "pd.DataFrame",
        # which mtypes do _fit/_predict support for X?
        "y_inner_mtype": "None",  # which mtypes do _fit/_predict support for y?
        "univariate-only": False,
        "fit_is_empty": False,
    }

    def __init__(self, transformer, columns=None):
        self.transformer = transformer
        self.columns = columns
        super().__init__()

        tags_to_clone = [
            "y_inner_mtype",
            "capability:inverse_transform",
            "handles-missing-data",
            "X-y-must-have-same-index",
            "transform-returns-same-time-index",
            "skip-inverse-transform",
        ]
        self.clone_tags(transformer, tag_names=tags_to_clone)

    def _fit(self, X, y=None):
        """Fit transformer to X and y.

        private _fit containing the core logic, called from fit

        Parameters
        ----------
        X : pd.DataFrame
            Data to fit transform to
        y : Series or Panel, default=None
            Additional data, e.g., labels for transformation

        Returns
        -------
        self: a fitted instance of the estimator
        """
        # check that columns are None or list of strings
        if self.columns is not None:
            if not isinstance(self.columns, list) and all(
                isinstance(s, str) for s in self.columns
            ):
                raise ValueError("Columns need to be a list of strings or None.")

        # set self.columns_ to columns that are going to be transformed
        # (all if self.columns is None)
        self.columns_ = self.columns
        if self.columns_ is None:
            self.columns_ = X.columns

        # make sure z contains all columns that the user wants to transform
        _check_columns(X, selected_columns=self.columns_)

        # fit by iterating over columns
        self.transformers_ = {}
        for colname in self.columns_:
            transformer = self.transformer.clone()
            self.transformers_[colname] = transformer
            self.transformers_[colname].fit(X[colname], y)
        return self

    def _transform(self, X, y=None):
        """Transform X and return a transformed version.

        private _transform containing the core logic, called from transform

        Returns a transformed version of X by iterating over specified
        columns and applying the wrapped transformer to them.

        Parameters
        ----------
        X : pd.DataFrame
            Data to be transformed
        y : Series or Panel, default=None
            Additional data, e.g., labels for transformation

        Returns
        -------
        Xt : pd.DataFrame
            transformed version of X
        """
        # make copy of z
        X = X.copy()

        # make sure z contains all columns that the user wants to transform
        _check_columns(X, selected_columns=self.columns_)
        for colname in self.columns_:
            X[colname] = self.transformers_[colname].transform(X[colname], y)
        return X

    def _inverse_transform(self, X, y=None):
        """Logic used by `inverse_transform` to reverse transformation on `X`.

        Returns an inverse-transformed version of X by iterating over specified
        columns and applying the univariate series transformer to them.
        Only works if `self.transformer` has an `inverse_transform` method.

        Parameters
        ----------
        X : pd.DataFrame
            Data to be inverse transformed
        y : Series or Panel, default=None
            Additional data, e.g., labels for transformation

        Returns
        -------
        Xt : pd.DataFrame
            inverse transformed version of X
        """
        # make copy of z
        X = X.copy()

        # make sure z contains all columns that the user wants to transform
        _check_columns(X, selected_columns=self.columns_)

        # iterate over columns that are supposed to be inverse_transformed
        for colname in self.columns_:
            X[colname] = self.transformers_[colname].inverse_transform(X[colname], y)

        return X

    def update(self, X, y=None, update_params=True):
        """Update parameters.

        Update the parameters of the estimator with new data
        by iterating over specified columns.
        Only works if `self.transformer` has an `update` method.

        Parameters
        ----------
        X : pd.Series
            New time series.
        update_params : bool, optional, default=True

        Returns
        -------
        self : an instance of self
        """
        z = check_series(X)

        # make z a pd.DataFrame in univariate case
        if isinstance(z, pd.Series):
            z = z.to_frame()

        # make sure z contains all columns that the user wants to transform
        _check_columns(z, selected_columns=self.columns_)
        for colname in self.columns_:
            self.transformers_[colname].update(z[colname], X)
        return self

    @classmethod
    def get_test_params(cls, parameter_set="default"):
        """Return testing parameter settings for the estimator.

        Parameters
        ----------
        parameter_set : str, default="default"
            Name of the set of test parameters to return, for use in tests. If no
            special parameters are defined for a value, will return `"default"` set.


        Returns
        -------
        params : dict or list of dict, default = {}
            Parameters to create testing instances of the class
            Each dict are parameters to construct an "interesting" test instance, i.e.,
            `MyClass(**params)` or `MyClass(**params[i])` creates a valid test instance.
            `create_test_instance` uses the first (or only) dictionary in `params`
        """
        from sktime.transformations.series.detrend import Detrender

        return {"transformer": Detrender()}


def _check_columns(z, selected_columns):
    # make sure z contains all columns that the user wants to transform
    z_wanted_keys = set(selected_columns)
    z_new_keys = set(z.columns)
    difference = z_wanted_keys.difference(z_new_keys)
    if len(difference) != 0:
        raise ValueError("Missing columns" + str(difference) + "in Z.")
