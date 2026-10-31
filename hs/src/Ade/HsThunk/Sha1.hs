-- | SHA-1 (FIPS 180-4) over a String's UTF-8 bytes. precompact_handoff's _safe_slug writes an
-- 8-hex digest taken from hashlib.sha1, so the Haskell hook needs the same digest to name the same
-- state directory as the Python one. Boot packages only.
module Ade.HsThunk.Sha1 (sha1Hex) where

import Data.Bits (complement, rotateL, shiftR, xor, (.&.), (.|.))
import Data.List (foldl')
import Data.Word (Word32, Word64, Word8)
import Numeric (showHex)
import qualified Data.ByteString as B
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE

sha1Hex :: String -> String
sha1Hex s = concatMap hex8 [h0, h1, h2, h3, h4]
  where
    msg = B.unpack (TE.encodeUtf8 (T.pack s))
    len = length msg
    padLen = (55 - len) `mod` 64
    bitLen = fromIntegral len * 8 :: Word64
    padded = msg ++ [0x80] ++ replicate padLen 0
             ++ [fromIntegral (bitLen `shiftR` (8 * i)) | i <- [7, 6 .. 0]]
    (h0, h1, h2, h3, h4) =
      foldl' block (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0) (chunks padded)
    hex8 w = let h = showHex w "" in replicate (8 - length h) '0' ++ h

chunks :: [a] -> [[a]]
chunks [] = []
chunks xs = let (a, b) = splitAt 64 xs in a : chunks b

be32 :: [Word8] -> Word32
be32 = foldl' (\acc b -> acc * 256 + fromIntegral b) 0

block :: (Word32, Word32, Word32, Word32, Word32) -> [Word8] -> (Word32, Word32, Word32, Word32, Word32)
block (a0, b0, c0, d0, e0) chunk = (a0 + a', b0 + b', c0 + c', d0 + d', e0 + e')
  where
    w0 = [be32 (take 4 (drop (4 * i) chunk)) | i <- [0 .. 15]]
    ws = w0 ++ [rotateL (ws !! (i - 3) `xor` ws !! (i - 8) `xor` ws !! (i - 14) `xor` ws !! (i - 16)) 1
               | i <- [16 .. 79 :: Int]]
    (a', b', c', d', e') = foldl' step (a0, b0, c0, d0, e0) (zip [0 :: Int ..] (take 80 ws))
    step (a, b, c, d, e) (t, wt) =
      let (f, k)
            | t < 20 = ((b .&. c) .|. (complement b .&. d), 0x5A827999)
            | t < 40 = (b `xor` c `xor` d, 0x6ED9EBA1)
            | t < 60 = ((b .&. c) .|. (b .&. d) .|. (c .&. d), 0x8F1BBCDC)
            | otherwise = (b `xor` c `xor` d, 0xCA62C1D6)
          temp = rotateL a 5 + f + e + k + wt
      in (temp, a, rotateL b 30, c, d)
