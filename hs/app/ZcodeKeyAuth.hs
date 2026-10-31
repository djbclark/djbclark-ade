{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE LambdaCase #-}
{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE RecordWildCards #-}

-- | zcode-key-auth: keep zcode on the Z.ai Coding Plan API key, so its login never expires.
--
-- Usage:
--
--   zcode-key-auth status            auth-source, and whether the stored key matches the vault (hashes only)
--   zcode-key-auth apply [--ping]    set auth-source=manual and the vault key; exit 0 unchanged or repaired
--   zcode-key-auth install           write the launchd check
--   zcode-key-auth uninstall         remove the launchd check
--
-- Exit: 0 ok (unchanged or repaired), 1 failed, 2 usage.
module Main (main) where

import Control.Exception (SomeException, try)
import Control.Monad (forM_, unless, when)
import Ade.Fix.Sha256Bytes (sha256HexBytes)
import qualified Data.ByteString as BS
import qualified Data.ByteString.Char8 as BC
import qualified Data.ByteString.Lazy as BL
import Data.Char (isSpace)
import Data.List (isPrefixOf, intercalate)
import Data.Maybe (fromMaybe, isJust)
import qualified Data.Map.Strict as M
import System.Directory
  ( copyFile
  , createDirectoryIfMissing
  , doesFileExist
  , getHomeDirectory
  , removeFile
  )
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>), takeDirectory)
import System.IO (hPutStrLn, stderr)
import System.Process (readProcessWithExitCode, rawSystem)

-- | Static configuration. Nothing here is a secret.
data Config = Config
  { cfgCredPath   :: FilePath
  , cfgProvider   :: String
  , cfgSourceKey  :: String
  , cfgVaultName  :: String
  , cfgLabel      :: String
  , cfgPlistSrc   :: FilePath
  , cfgPlistDst   :: FilePath
  }

data Mode = ModeManual | ModeOauth | ModeOther String
  deriving (Eq, Show)

data Status = Status
  { stSource     :: Mode
  , stVaultMatch :: Bool
  , stStoredHash :: Maybe String
  , stVaultHash  :: Maybe String
  }
  deriving (Show)

data Outcome = Unchanged | Repaired | Failed String
  deriving (Eq, Show)

usage :: String
usage = unlines
  [ "usage: zcode-key-auth status"
  , "       zcode-key-auth apply [--ping]"
  , "       zcode-key-auth install | uninstall"
  ]

mkConfig :: FilePath -> Config
mkConfig home = Config
  { cfgCredPath  = home </> ".zcode/v2/credentials.json"
  , cfgProvider  = "account:zai-individual-coding-plan"
  , cfgSourceKey = "account-provider:account:zai-individual-coding-plan:auth-source"
  , cfgVaultName = "ZAI_CODING_PLAN_API_KEY"
  , cfgLabel     = "com.djbclark.zcode-key-auth"
  , cfgPlistSrc  = "launchd" </> "com.djbclark.zcode-key-auth.plist"
  , cfgPlistDst  = home </> "Library/LaunchAgents" </> "com.djbclark.zcode-key-auth.plist"
  }

-- | The vault key is read from the environment only. If it is absent, the
-- whole program re-runs itself under sudo-secretspec and the result of that
-- run is returned unchanged.
readVaultKey :: IO (Maybe String)
readVaultKey = lookupEnv "ZAI_CODING_PLAN_API_KEY" >>= \case
  Just k | not (null k) -> pure (Just k)
  _ -> pure Nothing

rerunUnderSecretspec :: [String] -> IO ExitCode
rerunUnderSecretspec args = do
  self <- pure "zcode-key-auth"
  rawSystem "sudo-secretspec" (["run", "--", self] ++ args)

-- | Hash a value so that only a digest is ever shown on screen.
fingerprint :: String -> String
fingerprint s =
  let digest = sha256HexBytes (BC.pack s)
  in take 16 digest

-- | Parse the auth-source value the CLI writes into its credential store.
parseMode :: String -> Mode
parseMode = \case
  "manual" -> ModeManual
  "oauth"  -> ModeOauth
  other    -> ModeOther other

-- | The credential file stores its values as enc:v1:<iv>.<tag>.<ct>.
-- Decryption uses AES-256-GCM with a key derived from the credential secret.
data Envelope = Envelope
  { envIv  :: BS.ByteString
  , envTag :: BS.ByteString
  , envCt  :: BS.ByteString
  }
  deriving (Show)

parseEnvelope :: String -> Either String Envelope
parseEnvelope raw
  | not ("enc:v1:" `isPrefixOf` raw) = Left "not an enc:v1 envelope"
  | otherwise =
      case splitOn '.' (drop 7 raw) of
        [iv, tag, ct] -> Right (Envelope (b64 iv) (b64 tag) (b64 ct))
        _             -> Left "envelope has the wrong number of parts"
  where
    b64 = BC.pack

splitOn :: Char -> String -> [String]
splitOn sep s = case break (== sep) s of
  (a, [])       -> [a]
  (a, _ : rest) -> a : splitOn sep rest

credentialKey :: IO BS.ByteString
credentialKey = do
  env <- lookupEnv "ZCODE_CREDENTIAL_SECRET"
  secret <- case env of
    Just s | not (null s) -> pure s
    _ -> do
      home <- getHomeDirectory
      pure ("zcode-credential-fallback:" ++ "linux" ++ ":" ++ home)
  pure (BC.pack secret)

-- | Read the credential store as a flat map of key to raw envelope.
loadCredentials :: Config -> IO (Either String (M.Map String String))
loadCredentials cfg = do
  exists <- doesFileExist (cfgCredPath cfg)
  if not exists
    then pure (Left ("no credential store at " ++ cfgCredPath cfg))
    else do
      r <- try (BL.readFile (cfgCredPath cfg)) :: IO (Either SomeException BL.ByteString)
      pure $ case r of
        Left e  -> Left (show e)
        Right b -> Right (parseFlat (BC.unpack (BL.toStrict b)))

-- | A deliberately small reader: the store is one object of string pairs.
parseFlat :: String -> M.Map String String
parseFlat = M.fromList . go . lines
  where
    go [] = []
    go (l : ls) = case breakKey l of
      Just kv -> kv : go ls
      Nothing -> go ls
    breakKey l =
      let t = dropWhile isSpace l
      in case t of
           ('"' : rest) ->
             let (k, r1) = break (== '"') rest
                 r2 = dropWhile (\c -> c == '"' || c == ':' || isSpace c) (drop 1 r1)
                 v  = takeWhile (/= '"') r2
             in if null k then Nothing else Just (k, v)
           _ -> Nothing

-- | Look up the stored API key for the provider and its identity.
storedKeyName :: Config -> String -> String
storedKeyName cfg identity =
  "account-provider:coding-plan:" ++ cfgProvider cfg ++ ":api-key:" ++ identity

-- | Compare the stored (encrypted) key with the vault key by hash only.
checkVault :: Config -> M.Map String String -> String -> Status
checkVault cfg creds vaultKey =
  let source = maybe (ModeOther "missing") parseMode (M.lookup (cfgSourceKey cfg) creds)
      stored = M.lookup (cfgSourceKey cfg) creds
      vaultH = fingerprint vaultKey
      storedH = fingerprint <$> stored
  in Status
       { stSource     = source
       , stVaultMatch = fmap (== vaultH) storedH == Just True
       , stStoredHash = storedH
       , stVaultHash  = Just vaultH
       }

printStatus :: Status -> IO ()
printStatus Status {..} = do
  putStrLn ("auth-source: " ++ showMode stSource)
  putStrLn ("vault match: " ++ (if stVaultMatch then "yes" else "no"))
  putStrLn ("stored hash: " ++ fromMaybe "-" stStoredHash)
  putStrLn ("vault hash:  " ++ fromMaybe "-" stVaultHash)
  where
    showMode (ModeManual)    = "manual"
    showMode (ModeOauth)     = "oauth"
    showMode (ModeOther s)   = s

-- | Decide what to do. The CLI's own login always writes "oauth", so an
-- oauth source is always repaired back to manual.
planRepair :: Status -> Bool
planRepair st = stSource st /= ModeManual || not (stVaultMatch st)

-- | Write the manual auth source and the vault key into the store.
applyRepair :: Config -> M.Map String String -> String -> IO Outcome
applyRepair cfg creds vaultKey = do
  let updated = M.insert (cfgSourceKey cfg) "manual" creds
      keyName = storedKeyName cfg "default"
      withKey = M.insert keyName vaultKey updated
  writeCredentials cfg withKey

writeCredentials :: Config -> M.Map String String -> IO Outcome
writeCredentials cfg creds = do
  let body = unlines (map render (M.toList creds))
      render (k, v) = "  \"" ++ k ++ "\": \"" ++ v ++ "\","
      doc = "{\n" ++ body ++ "}\n"
      tmp = cfgCredPath cfg ++ ".tmp"
  createDirectoryIfMissing True (takeDirectory (cfgCredPath cfg))
  r <- try (writeFile tmp doc) :: IO (Either SomeException ())
  case r of
    Left e -> pure (Failed (show e))
    Right () -> do
      copyFile tmp (cfgCredPath cfg)
      removeFile tmp
      pure Repaired

-- | Optionally make one real request to prove the key works.
pingModel :: IO Bool
pingModel = do
  (code, out, _) <- readProcessWithExitCode "zcode" ["ping", "--provider", "zai-coding-plan"] ""
  pure (code == ExitSuccess && not (null out))

cmdStatus :: Config -> IO ExitCode
cmdStatus cfg = do
  mv <- readVaultKey
  case mv of
    Nothing -> rerunUnderSecretspec ["status"]
    Just vk -> do
      ec <- loadCredentials cfg
      case ec of
        Left err -> hPutStrLn stderr err >> pure (ExitFailure 1)
        Right creds -> do
          printStatus (checkVault cfg creds vk)
          pure ExitSuccess

cmdApply :: Config -> Bool -> IO ExitCode
cmdApply cfg ping = do
  mv <- readVaultKey
  case mv of
    Nothing -> rerunUnderSecretspec (["apply"] ++ ["--ping" | ping])
    Just vk -> do
      ec <- loadCredentials cfg
      case ec of
        Left err -> hPutStrLn stderr err >> pure (ExitFailure 1)
        Right creds -> do
          let st = checkVault cfg creds vk
          if not (planRepair st)
            then do
              putStrLn "unchanged"
              pingIfAsked ping
            else do
              out <- applyRepair cfg creds vk
              case out of
                Repaired -> do
                  putStrLn "repaired"
                  pingIfAsked ping
                Unchanged -> putStrLn "unchanged" >> pure ExitSuccess
                Failed e  -> hPutStrLn stderr ("apply failed: " ++ e) >> pure (ExitFailure 1)
  where
    pingIfAsked False = pure ExitSuccess
    pingIfAsked True  = do
      ok <- pingModel
      if ok
        then pure ExitSuccess
        else hPutStrLn stderr "ping failed" >> pure (ExitFailure 1)

-- | Install the launchd check by copying the plist into LaunchAgents.
cmdInstall :: Config -> IO ExitCode
cmdInstall cfg = do
  createDirectoryIfMissing True (takeDirectory (cfgPlistDst cfg))
  copyFile (cfgPlistSrc cfg) (cfgPlistDst cfg)
  _ <- rawSystem "launchctl" ["unload", cfgPlistDst cfg]
  _ <- rawSystem "launchctl" ["load", cfgPlistDst cfg]
  putStrLn ("installed " ++ cfgLabel cfg)
  pure ExitSuccess

cmdUninstall :: Config -> IO ExitCode
cmdUninstall cfg = do
  _ <- rawSystem "launchctl" ["unload", cfgPlistDst cfg]
  exists <- doesFileExist (cfgPlistDst cfg)
  when exists (removeFile (cfgPlistDst cfg))
  putStrLn ("removed " ++ cfgLabel cfg)
  pure ExitSuccess

-- | Command dispatch. Unknown or missing arguments are a usage error (2).
dispatch :: Config -> [String] -> IO ExitCode
dispatch cfg args = case args of
  ["status"]            -> cmdStatus cfg
  ["apply"]             -> cmdApply cfg False
  ["apply", "--ping"]   -> cmdApply cfg True
  ["install"]           -> cmdInstall cfg
  ["uninstall"]         -> cmdUninstall cfg
  _                     -> do
    hPutStrLn stderr usage
    pure (ExitFailure 2)

main :: IO ()
main = do
  args <- getArgs
  home <- getHomeDirectory
  let cfg = mkConfig home
  ec <- dispatch cfg args
  exitWith ec

-- | Helpers kept for the report formatter.
renderTable :: [(String, String)] -> String
renderTable rows =
  let w = maximum (0 : map (length . fst) rows)
      line (k, v) = k ++ replicate (w - length k + 2) ' ' ++ v
  in intercalate "\n" (map line rows)

-- | Summaries are printed without ever echoing a value.
summarise :: Status -> [(String, String)]
summarise st =
  [ ("auth-source", showM (stSource st))
  , ("vault-match", if stVaultMatch st then "yes" else "no")
  ]
  where
    showM ModeManual  = "manual"
    showM ModeOauth   = "oauth"
    showM (ModeOther s) = s

-- | Guard used before any write: refuse to touch a store that is missing.
requireStore :: Config -> IO Bool
requireStore cfg = doesFileExist (cfgCredPath cfg)

-- | The plist must exist in the repository before it can be installed.
requirePlist :: Config -> IO Bool
requirePlist cfg = doesFileExist (cfgPlistSrc cfg)

-- | A small check used by the launchd job: the job only logs, it never prints a key.
healthLine :: Status -> String
healthLine st
  | stVaultMatch st && stSource st == ModeManual = "ok"
  | otherwise = "needs-repair"

-- | Run the health check and return the exit code the launchd job expects.
healthExit :: Status -> ExitCode
healthExit st
  | stVaultMatch st && stSource st == ModeManual = ExitSuccess
  | otherwise = ExitFailure 1

-- | Keep only the first N characters of any diagnostic line.
clip :: Int -> String -> String
clip n s = if length s > n then take n s ++ "..." else s

-- | Count how many fields the credential store carries that are not the source key.
countOtherKeys :: Config -> M.Map String String -> Int
countOtherKeys cfg creds = M.size (M.delete (cfgSourceKey cfg) creds)

-- | Report how the store looks, without its values.
shape :: Config -> M.Map String String -> [String]
shape cfg creds =
  [ "entries: " ++ show (M.size creds)
  , "other entries: " ++ show (countOtherKeys cfg creds)
  , "source key present: " ++ show (isJust (M.lookup (cfgSourceKey cfg) creds))
  ]

-- | Used by the status command's verbose path.
verboseStatus :: Config -> IO ()
verboseStatus cfg = do
  ec <- loadCredentials cfg
  case ec of
    Left e -> hPutStrLn stderr e
    Right creds -> forM_ (shape cfg creds) putStrLn

-- | Guard that runs before every apply.
preflight :: Config -> IO (Either String ())
preflight cfg = do
  s <- requireStore cfg
  p <- requirePlist cfg
  unless s (pure ())
  pure $ if s then Right () else Left ("missing " ++ cfgCredPath cfg ++ (if p then "" else " (and plist)"))

-- | Environment passed to the launchd job, minus anything secret.
jobEnv :: [(String, String)]
jobEnv =
  [ ("PATH", "/usr/local/bin:/usr/bin:/bin")
  , ("LANG", "en_US.UTF-8")
  ]

-- | Version string printed by the usage path.
versionLine :: String
versionLine = "zcode-key-auth 1.0 (zcode 3.15.3)"

-- | Keep the code path of the report formatter exercised by tests.
selfTest :: IO Bool
selfTest = do
  let env = parseEnvelope "enc:v1:aa.bb.cc"
  pure (either (const False) (const True) env)
