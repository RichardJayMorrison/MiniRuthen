"""Utils holds miscellaneous classes and functions that don't fit elsewhere."""

import bisect
import collections
import math
import world

class YearRecord(object):
  def __init__(self):
    # Initialize the lists of deposits, withdrawals, and incomes
    self.withdrawals = []
    self.deposits = []
    self.incomes = []
    self.tax_receipts = []

    self.year = world.BASE_YEAR
    self.growth_rate = 0
    self.age = world.START_AGE
    self.rrsp_room = 0
    self.tfsa_room = 0

    self.is_dead = False
    self.is_employed = False
    self.is_retired = False

LifetimeRecord = collections.namedtuple('LifetimeRecord',
    [])

def Indexed(base, current_year, rate=1+world.PARGE):
  return base * (rate ** (current_year - world.BASE_YEAR))

class SummaryStatsAccumulator(object):
  """This uses a generalization of Welford's Algorithm by Chan et al [1] to
  calculate mean, variance, and standard deviation in one pass, with the ability
  to update from intermediate objects of this class as well as from single
  data points.

  [1] http://i.stanford.edu/pub/cstr/reports/cs/tr/79/773/CS-TR-79-773.pdf
  """
  def __init__(self):
    self.n = 0
    self.mean = 0
    self.M2 = 0

  def UpdateOneValue(self, value):
    self.n += 1
    delta = value - self.mean
    self.mean += delta / self.n
    self.M2 += delta * (value - self.mean)

  def UpdateSubsample(self, n, mean, M2):
    if not (self.n or n):
      return
    delta = mean - self.mean
    self.mean = (self.mean * self.n + mean * n) / (self.n + n)
    self.M2 += M2 + math.pow(delta, 2) * self.n * n / (self.n + n)
    self.n += n

  def UpdateAccumulator(self, acc):
    self.UpdateSubsample(acc.n, acc.mean, acc.M2)

  @property
  def variance(self):
    """Returns the sample variance, or NaN if fewer than 2 updates."""
    if self.n > 1:
      return self.M2 / (self.n - 1)
    else:
      return float('nan')

  @property
  def stddev(self):
    """Returns the sample standard deviation, or NaN if fewer than 2 updates."""
    return math.sqrt(self.variance)


class QuantileAccumulator(object):
  """This uses a streaming parallel histogram building algorithm described by
  Ben-Haim and Yom-Tov in [1] to accumulate values, and uses this histogram to
  provide quantile approximations.

  [1] http://jmlr.org/papers/volume11/ben-haim10a/ben-haim10a.pdf
  """
  def __init__(self, max_bins=100):
    self.max_bins = max_bins
    self.bins = []

  def _Merge(self):
    """Merges bins if there are more than max_bins. Expects self.bins to be sorted"""
    while len(self.bins) > self.max_bins:
      # Find the two closest bins
      sep, i = min((self.bins[i+1][0] - self.bins[i][0], i) for i in range(len(self.bins)-1))

      # Merge them
      self.bins[i:i+2] = [(
          (self.bins[i][0]*self.bins[i][1] + self.bins[i+1][0]*self.bins[i+1][1])/(self.bins[i][1]+self.bins[i+1][1]),
          self.bins[i][1]+self.bins[i+1][1])]

  def UpdateOneValue(self, value):
    i = bisect.bisect_left(self.bins, (value, 1))
    if i < len(self.bins) and self.bins[i][0] == value:
      self.bins[i] = (value, self.bins[i][1]+1)
    else:
      self.bins.insert(i, (value, 1))
    self._Merge()

  def UpdateHistogram(self, bins):
    self.bins.extend(bins)
    self.bins.sort()
    self._Merge()

  def Quantile(self, q):
    if q < 0 or 1 < q:
      raise ValueError("quantile should be a number between 0 and 1, inclusive")

    # Cumulative sum of the counts at each bin point, treating the point as the center of the bin
    bin_counts = [0] + [b[1] for b in self.bins] + [0]
    cumsums = [0]
    for i in range(1, len(bin_counts)):
      bin_count = (bin_counts[i] + bin_counts[i-1])/2
      cumsums.append(cumsums[-1] + bin_count)

    # Find the index of the interval in which the desired quantile lies
    n_points = q * cumsums[-1]
    i = bisect.bisect(cumsums, n_points)-1

    if i <= 0:
      # special case, quantile falls before first bin
      return self.bins[0][0]
    elif i >= len(self.bins):
      # Special case, quantile falls at or after last bin
      return self.bins[-1][0]
    else:
      bin_frac = (n_points - cumsums[i])/(cumsums[i+1] - cumsums[i])
      return self.bins[i-1][0] + bin_frac * (self.bins[i][0] - self.bins[i-1][0])

class AccumulatorBundle(object):
  def __init__(self):
    # Fitness function component accumulators
    self.lifetime_consumption_summary = SummaryStatsAccumulator()
    self.lifetime_consumption_hist = QuantileAccumulator()
    self.working_consumption_summary = SummaryStatsAccumulator()
    self.working_consumption_hist = QuantileAccumulator()
    self.retired_consumption_summary = SummaryStatsAccumulator()
    self.retired_consumption_hist = QuantileAccumulator()
    self.pre_disability_retired_consumption_summary = SummaryStatsAccumulator()
    self.discounted_lifetime_consumption_summary = SummaryStatsAccumulator()
    self.earnings_late_working = SummaryStatsAccumulator()

    self.persons = 0
    self.working_years = 0
    self.retirement_years = 0
    self.retired_persons = 0
    self.seniors = 0
    self.seniors_years = 0
    self.retirement_years_ruined = 0
    self.retirees_experiencing_ruin = 0
    self.ruined_persons = 0
    self.retirement_years_below_ympe_assets = 0
    self.retirement_years_below_twice_ympe_assets = 0
    self.seniors_receiving_gis = 0
    self.seniors_years_receiving_gis = 0
    self.gis_received = 0
    self.retirees_experiencing_income_less_than_lico = 0
    self.retirement_years_below_lico_income = 0
    self.retired_lico_gap = 0
    self.working_lico_gap = 0
    self.underwithdrawers = 0
    self.aggregate_retirement_withdrawals_less_retirement_assets = 0
    self.aggregate_retirement_withdrawals_less_lifetime_savings = 0
    self.after_tax_estate_at_death = 0

  def UpdateConsumption(self, consumption, year, is_retired):
    discounted_consumption = Indexed(consumption, year, 1-world.DISCOUNT_RATE)
    age = year - world.BASE_YEAR + world.START_AGE

    self.lifetime_consumption_summary.UpdateOneValue(consumption)
    self.lifetime_consumption_hist.UpdateOneValue(consumption)
    self.discounted_lifetime_consumption_summary.UpdateOneValue(discounted_consumption)
    if is_retired:
      self.retired_consumption_summary.UpdateOneValue(consumption)
      self.retired_consumption_hist.UpdateOneValue(consumption)
      if age <= world.AVG_DISABILITY_AGE:
        self.pre_disability_retired_consumption_summary.UpdateOneValue(consumption)
    else:
      self.working_consumption_summary.UpdateOneValue(consumption)
      self.working_consumption_hist.UpdateOneValue(consumption)

  def Merge(self, bundle):
    """Merge in another AccumulatorBundle."""
    self.lifetime_consumption_summary.UpdateAccumulator(bundle.lifetime_consumption_summary)
    self.lifetime_consumption_hist.UpdateHistogram(bundle.lifetime_consumption_hist.bins)
    self.working_consumption_summary.UpdateAccumulator(bundle.working_consumption_summary)
    self.working_consumption_hist.UpdateHistogram(bundle.working_consumption_hist.bins)
    self.retired_consumption_summary.UpdateAccumulator(bundle.retired_consumption_summary)
    self.retired_consumption_hist.UpdateHistogram(bundle.retired_consumption_hist.bins)
    self.pre_disability_retired_consumption_summary.UpdateAccumulator(bundle.pre_disability_retired_consumption_summary)
    self.discounted_lifetime_consumption_summary.UpdateAccumulator(bundle.discounted_lifetime_consumption_summary)

    self.persons += bundle.persons
    self.working_years += bundle.working_years
    self.retirement_years += bundle.retirement_years
    self.retired_persons += bundle.retired_persons
    self.seniors += bundle.seniors
    self.seniors_years += bundle.seniors_years
    self.retirement_years_ruined += bundle.retirement_years_ruined
    self.retirees_experiencing_ruin += bundle.retirees_experiencing_ruin
    self.ruined_persons += bundle.ruined_persons
    self.retirement_years_below_ympe_assets += bundle.retirement_years_below_ympe_assets
    self.retirement_years_below_twice_ympe_assets += bundle.retirement_years_below_twice_ympe_assets
    self.seniors_receiving_gis += bundle.seniors_receiving_gis
    self.seniors_years_receiving_gis += bundle.seniors_years_receiving_gis
    self.gis_received += bundle.gis_received
    self.retirees_experiencing_income_less_than_lico += bundle.retirees_experiencing_income_less_than_lico
    self.retirement_years_below_lico_income += bundle.retirement_years_below_lico_income
    self.retired_lico_gap += bundle.retired_lico_gap
    self.working_lico_gap += bundle.working_lico_gap
    self.underwithdrawers += bundle.underwithdrawers
    self.aggregate_retirement_withdrawals_less_retirement_assets += bundle.aggregate_retirement_withdrawals_less_retirement_assets
    self.aggregate_retirement_withdrawals_less_lifetime_savings += bundle.aggregate_retirement_withdrawals_less_lifetime_savings
    self.after_tax_estate_at_death += bundle.after_tax_estate_at_death
