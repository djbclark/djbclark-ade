module Main (main) where

import Control.Monad (forM_, unless, when)
import Data.Char (isAlphaNum, isSpace)
import Data.List (isInfixOf, isPrefixOf, intercalate)
import Data.Maybe (mapMaybe)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hPutStr, hPutStrLn, stderr)

-- | The commands the gate is willing to forward to the hermes host.
data Allowed
  = StatusOnly
  | ReloadConfig
  | RotateLog
  deriving (Eq, Show, Enum, Bounded)

-- | Result of checking one requested command line.
data Decision
  = Permit Allowed
  | Deny String
  deriving (Eq, Show)

-- | Exit codes: 0 forwarded, 77 refused by policy, 2 usage.
exitForwarded, exitRefused, exitUsage :: Int
exitForwarded = 0
exitRefused = 77
exitUsage = 2

-- | The literal commands the gate accepts, keyed to their allowed kind.
table :: [(String, Allowed)]
table =
  [ ("hermes status", StatusOnly)
  , ("hermes reload-config", ReloadConfig)
  , ("hermes rotate-log", RotateLog)
  ]

-- | Characters we never let into a forwarded command.
forbiddenChars :: String
forbiddenChars = ";|&`$<>(){}\\\"'\n\r"

hasForbidden :: String -> Bool
hasForbidden = any (`elem` forbiddenChars)

-- | Collapse runs of whitespace to single spaces and trim the ends.
normalise :: String -> String
normalise = unwords . words

-- | Decide whether a command line may be forwarded.
decide :: String -> Decision
decide raw
  | null cmd = Deny "empty command"
  | hasForbidden cmd = Deny "shell metacharacters are not allowed"
  | length cmd > 120 = Deny "command too long"
  | otherwise = case lookup cmd table of
      Just kind -> Permit kind
      Nothing -> Deny ("not on the allow list: " ++ cmd)
  where
    cmd = normalise raw

-- | Words of the forwarded command, for logging.
argvOf :: Allowed -> [String]
argvOf StatusOnly = ["hermes", "status"]
argvOf ReloadConfig = ["hermes", "reload-config"]
argvOf RotateLog = ["hermes", "rotate-log"]

-- | Render a decision for the audit line.
renderDecision :: Decision -> String
renderDecision (Permit k) = "permit " ++ unwords (argvOf k)
renderDecision (Deny why) = "deny: " ++ why

-- | Exit code that corresponds to a decision.
codeFor :: Decision -> ExitCode
codeFor (Permit _) = ExitSuccess
codeFor (Deny _) = ExitFailure exitRefused

-- | The SSH original command is supplied by sshd in SSH_ORIGINAL_COMMAND.
originalCommand :: [String] -> Maybe String
originalCommand [] = Nothing
originalCommand (x : _) = Just x

-- | Pull the target host alias from an argument, if one is present.
hostAlias :: [String] -> Maybe String
hostAlias args =
  case [ a | a <- args, "--host=" `isPrefixOf` a ] of
    (a : _) -> Just (drop (length "--host=") a)
    [] -> Nothing

-- | Only a fixed set of host aliases are accepted.
knownHosts :: [String]
knownHosts = ["hermes", "hermes-lab"]

validHost :: String -> Bool
validHost h = h `elem` knownHosts && all (\c -> isAlphaNum c || c == '-') h

-- | Build the audit line that goes to the log.
auditLine :: String -> Decision -> String
auditLine who d = "gate " ++ who ++ " " ++ renderDecision d

-- | Sanitise a free-text reason before it is logged.
logSafe :: String -> String
logSafe = map (\c -> if isSpace c then ' ' else c) . take 200

-- | Parse the allow-list from text, one "command = kind" per line.
parseList :: String -> [(String, Allowed)]
parseList txt = mapMaybe parseLine (lines txt)
  where
    parseLine l =
      case break (== '=') l of
        (c, '=' : k) -> do
          kind <- lookup (normalise k) kinds
          pure (normalise c, kind)
        _ -> Nothing
    kinds = [ (show k, k) | k <- [minBound .. maxBound] ]

-- | Whether a parsed allow-list matches the built-in table exactly.
matchesBuiltin :: [(String, Allowed)] -> Bool
matchesBuiltin xs = all (`elem` table) xs && length xs == length table

-- | The number of commands on the allow list.
allowCount :: Int
allowCount = length table

-- | Shows the allow list as a block of text for --list.
listText :: String
listText = intercalate "\n" [ c ++ "  (" ++ show k ++ ")" | (c, k) <- table ]

-- | A reason string for a denial, used in the audit line.
denyReason :: Decision -> Maybe String
denyReason (Deny r) = Just r
denyReason _ = Nothing

-- | Checks a list of candidate commands and returns the first permitted one.
firstPermitted :: [String] -> Maybe (String, Allowed)
firstPermitted [] = Nothing
firstPermitted (c : cs) =
  case decide c of
    Permit k -> Just (c, k)
    Deny _ -> firstPermitted cs

-- | Forwarding is a pure description here: it returns what would be run.
forwardPlan :: Allowed -> [String]
forwardPlan k = ["ssh", "hermes"] ++ argvOf k

-- | Format a plan as one shell-free line for display only.
planLine :: Allowed -> String
planLine = unwords . forwardPlan

-- | A small self check run by the gate's test script.
selfCheck :: Bool
selfCheck =
  and
    [ isPermit (decide "hermes status")
    , isDeny (decide "hermes status; rm -rf /")
    , isDeny (decide "")
    , isDeny (decide "hermes delete-everything")
    , isPermit (decide "  hermes   reload-config  ")
    ]
  where
    isPermit (Permit _) = True
    isPermit _ = False
    isDeny (Deny _) = True
    isDeny _ = False

-- | Reject any host alias that is not known.
checkHost :: [String] -> Either String String
checkHost args =
  case hostAlias args of
    Nothing -> Right "hermes"
    Just h
      | validHost h -> Right h
      | otherwise -> Left ("unknown host alias: " ++ logSafe h)

-- | The main decision path, factored for testing.
gateOnce :: String -> String -> (Decision, [String])
gateOnce who raw =
  let d = decide raw
      msg = auditLine who d
  in (d, [msg])

-- | Logs the audit lines to stderr.
audit :: [String] -> IO ()
audit = mapM_ (hPutStrLn stderr)

usage :: String
usage = unlines
  [ "usage: change-hermes-ssh-gate [--host=ALIAS] [--list] [--self-check]"
  , "  reads SSH_ORIGINAL_COMMAND from the environment when no argument is given"
  , "  exit 0 forwarded, 77 refused, 2 usage"
  ]

main :: IO ()
main = do
  args <- getArgs
  when ("--list" `elem` args) $ do
    putStrLn listText
    exitWith ExitSuccess
  when ("--self-check" `elem` args) $ do
    putStrLn (if selfCheck then "self-check ok" else "self-check FAILED")
    exitWith (if selfCheck then ExitSuccess else ExitFailure 1)
  case checkHost args of
    Left err -> do
      hPutStrLn stderr err
      hPutStr stderr usage
      exitWith (ExitFailure exitUsage)
    Right host -> do
      let raw = maybe "" id (originalCommand (filter (not . ("--" `isPrefixOf`)) args))
          (d, logs) = gateOnce host raw
      audit logs
      case d of
        Permit k -> do
          putStrLn (planLine k)
          exitWith (codeFor d)
        Deny why -> do
          hPutStrLn stderr ("refused: " ++ why)
          exitWith (codeFor d)

-- | Keeps the shape of a log line stable for grep.
logPrefix :: String
logPrefix = "change-hermes-ssh-gate"

-- | Full log line for a decision.
logLine :: String -> Decision -> String
logLine who d = logPrefix ++ " " ++ auditLine who d

-- | Checks that a command does not contain an embedded newline.
singleLine :: String -> Bool
singleLine s = not ('\n' `elem` s) && not ('\r' `elem` s)

-- | Returns the reason a command was refused, if it was.
refusalFor :: String -> Maybe String
refusalFor raw = denyReason (decide raw)

-- | True if the command mentions a privileged verb anywhere.
mentionsPrivileged :: String -> Bool
mentionsPrivileged raw = any (`isInfixOf` raw) ["sudo", "chmod", "chown", "passwd"]

-- | Extra check layered on the allow list for privileged words.
decideStrict :: String -> Decision
decideStrict raw
  | mentionsPrivileged raw = Deny "privileged verb"
  | otherwise = decide raw

-- | Batch variant that reports every refusal in a list.
decideAll :: [String] -> [(String, Decision)]
decideAll cs = [ (c, decideStrict c) | c <- cs ]

-- | Print each batch result on its own line.
printBatch :: [(String, Decision)] -> IO ()
printBatch rs =
  forM_ rs $ \(c, d) -> putStrLn (c ++ " => " ++ renderDecision d)

-- | Count of refusals in a batch.
refusalCount :: [(String, Decision)] -> Int
refusalCount rs = length [ () | (_, Deny _) <- rs ]

-- | Whether any command in a batch was refused.
anyRefused :: [(String, Decision)] -> Bool
anyRefused rs = refusalCount rs > 0

-- | Exit code for a batch: refused if any command was.
batchCode :: [(String, Decision)] -> ExitCode
batchCode rs = if anyRefused rs then ExitFailure exitRefused else ExitSuccess

-- | Length of the longest allowed command, for column alignment.
widestAllowed :: Int
widestAllowed = maximum (map (length . fst) table)

-- | Pads a string to the widest allowed command.
padCommand :: String -> String
padCommand s = s ++ replicate (widestAllowed - length s) ' '

-- | Table with aligned columns for --list.
alignedList :: [String]
alignedList = [ padCommand c ++ "  " ++ show k | (c, k) <- table ]

-- | Verifies that every table entry is itself permitted.
tableIsSelfConsistent :: Bool
tableIsSelfConsistent = all (\(c, _) -> isPermitted (decide c)) table
  where
    isPermitted (Permit _) = True
    isPermitted _ = False

-- | Whether the built-in table is ready to ship.
readyToShip :: Bool
readyToShip = tableIsSelfConsistent && selfCheck && allowCount > 0

-- | Report line for the readiness check.
readinessLine :: String
readinessLine = if readyToShip then "ready" else "not ready"

-- | Reads an allow list file, returning an error on malformed input.
loadAllowFile :: FilePath -> IO (Either String [(String, Allowed)])
loadAllowFile path = do
  txt <- readFile path
  let parsed = parseList txt
  pure $ if null parsed
    then Left "allow list is empty or malformed"
    else Right parsed

-- | Merges an extra allow list into the built-in table, without duplicates.
mergeAllow :: [(String, Allowed)] -> [(String, Allowed)]
mergeAllow extra = table ++ [ e | e <- extra, e `notElem` table ]

-- | Sorted view of the merged allow list.
sortedAllow :: [(String, Allowed)] -> [(String, Allowed)]
sortedAllow = foldr insertSorted []
  where
    insertSorted x [] = [x]
    insertSorted x (y : ys)
      | fst x <= fst y = x : y : ys
      | otherwise = y : insertSorted x ys

-- | Human summary of how many commands a list permits.
summarizeAllow :: [(String, Allowed)] -> String
summarizeAllow xs = show (length xs) ++ " commands permitted"

-- | Trims a log message to a fixed length.
clipLog :: Int -> String -> String
clipLog n s = if length s > n then take n s else s

-- | Escapes nothing: the gate only ever prints fixed strings.
echoPlan :: Allowed -> IO ()
echoPlan k = putStrLn (planLine k)

-- | Whether the environment looks like the expected hermes login.
loginLooksRight :: Maybe String -> Bool
loginLooksRight (Just u) = u `elem` ["hermes", "ops"]
loginLooksRight Nothing = False

-- | Final guard: a command must be a single permitted line.
finalGuard :: String -> Either String Allowed
finalGuard raw
  | not (singleLine raw) = Left "embedded line break"
  | otherwise = case decideStrict raw of
      Permit k -> Right k
      Deny why -> Left why

-- | Runs the final guard and reports the result as text.
guardReport :: String -> String
guardReport raw = either ("refused: " ++) (("permitted: " ++) . unwords . argvOf) (finalGuard raw)

-- | Placeholder for the audit sink; the real sink is stderr.
sinkName :: String
sinkName = "stderr"

-- | Whether a given word is a reserved gate keyword.
reservedWord :: String -> Bool
reservedWord w = w `elem` ["gate", "hermes", "permit", "deny"]

-- | Reserved words found in a free-text reason.
reservedIn :: String -> [String]
reservedIn s = filter reservedWord (words s)

-- | Checks an allow entry's name for reserved words.
entryClean :: (String, Allowed) -> Bool
entryClean (c, _) = null (reservedIn c) || c `elem` map fst table

-- | Every entry in a list must be clean.
listClean :: [(String, Allowed)] -> Bool
listClean = all entryClean

-- | Closing check used by the self test runner.
closing :: IO ()
closing = unless readyToShip (hPutStrLn stderr "gate: not ready")
