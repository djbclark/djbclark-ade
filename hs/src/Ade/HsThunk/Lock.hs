{-# LANGUAGE ForeignFunctionInterface #-}
-- | An exclusive flock(2) on a lock file, the same lock the Python hooks take with fcntl.flock, so
-- the two tracks exclude each other on one file. `unix` has no flock, so this is one foreign call
-- into libc and nothing else leaves Haskell.
module Ade.HsThunk.Lock (withFlock) where

import Control.Concurrent (threadDelay)
import Control.Exception (SomeException, bracket, try)
import Data.Bits ((.|.))
import Foreign.C.Types (CInt (..))
import System.Posix.IO (OpenFileFlags (..), OpenMode (..), closeFd, defaultFileFlags, openFd)
import System.Posix.Types (Fd (..))

foreign import ccall unsafe "flock" c_flock :: CInt -> CInt -> IO CInt

lockEx, lockNb :: CInt
lockEx = 2
lockNb = 4

-- | Run the action with the flock held (True), or with it not had (False) after `retries` tries
-- `waitMicro` apart. The lock file is created when missing and kept; closing the descriptor drops
-- the lock. An unopenable lock file is "not held", never an exception.
withFlock :: FilePath -> Int -> Int -> (Bool -> IO a) -> IO a
withFlock path retries waitMicro act = do
  opened <- try (openFd path WriteOnly defaultFileFlags { append = True, creat = Just 0o644 })
              :: IO (Either SomeException Fd)
  case opened of
    Left _ -> act False
    Right fd -> bracket (pure fd) closeFd $ \(Fd cfd) -> do
      held <- tryLock cfd retries
      act held
  where
    tryLock _ 0 = pure False
    tryLock cfd n = do
      rc <- c_flock cfd (lockEx .|. lockNb)
      if rc == 0
        then pure True
        else threadDelay waitMicro >> tryLock cfd (n - 1 :: Int)
