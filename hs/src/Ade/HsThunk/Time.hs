-- | Time helpers for the hs-thunk hook ports. parseIso is the subset of Python's
-- datetime.fromisoformat that the hooks' stamps use (a naive stamp counts as UTC, as _parse does).
-- nyLocal gives America/New_York for quota_nudge's profile line. `time` has no zone database, so
-- the US rule is written out: DST from the second Sunday of March to the first Sunday of November
-- (since 2007), 02:00 local on each switch. Boot packages only.
module Ade.HsThunk.Time (parseIso, nyLocal) where

import Data.Maybe (catMaybes, listToMaybe)
import Data.Time

-- | Parse an ISO-8601 stamp; a trailing Z reads as +00:00.
parseIso :: String -> Maybe UTCTime
parseIso raw = listToMaybe (catMaybes [parseAs f s | f <- formats])
  where
    s = concatMap (\c -> if c == 'Z' then "+00:00" else [c]) raw
    formats =
      [ "%Y-%m-%dT%H:%M:%S%Q%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%Q"
      , "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S%Q%z", "%Y-%m-%d %H:%M:%S%Q", "%Y-%m-%d" ]

parseAs :: String -> String -> Maybe UTCTime
parseAs f s = parseTimeM True defaultTimeLocale f s

-- | The New York wall-clock instant (shifted to a UTCTime that reads as local time) and its label.
nyLocal :: UTCTime -> (UTCTime, String)
nyLocal t
  | t >= start && t < end = (addUTCTime (-4 * 3600) t, "EDT")
  | otherwise = (addUTCTime (-5 * 3600) t, "EST")
  where
    (y, _, _) = toGregorian (utctDay t)
    start = UTCTime (addDays 7 (firstSunday (fromGregorian y 3 1))) (secondsToDiffTime (7 * 3600))
    end = UTCTime (firstSunday (fromGregorian y 11 1)) (secondsToDiffTime (6 * 3600))
    firstSunday d = head [x | x <- iterate (addDays 1) d, dayOfWeek x == Sunday]
