-- | SHA-256 (FIPS 180-4) over a String's UTF-8 bytes, for tools that keep hashes the Python
-- versions wrote (hashlib.sha256(...).hexdigest()). Boot packages only.
module Ade.Sha256 (sha256Hex) where

import Data.Bits (complement, rotateR, shiftL, shiftR, xor, (.&.), (.|.))
import Data.Char (ord)
import Data.List (foldl')
import Data.Word (Word32, Word64, Word8)
import Numeric (showHex)
import qualified Data.ByteString as B
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE

sha256Hex :: String -> String
sha256Hex s = concatMap hex8 (digest (B.unpack (TE.encodeUtf8 (T.pack s))))
  where
    hex8 w = let h = showHex w "" in replicate (8 - length h) '0' ++ h

k256 :: [Word32]
k256 =
  [ 0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5
  , 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174
  , 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da
  , 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967
  , 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85
  , 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070
  , 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3
  , 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]

padMessage :: [Word8] -> [Word8]
padMessage bs =
  let len = fromIntegral (length bs) * 8 :: Word64
      zeros = (55 - length bs) `mod` 64
   in bs ++ [0x80] ++ replicate zeros 0 ++ [fromIntegral (len `shiftR` (8 * i)) | i <- [7, 6 .. 0]]

be32 :: [Word8] -> Word32
be32 = foldl' (\acc b -> (acc `shiftL` 8) .|. fromIntegral b) 0

digest :: [Word8] -> [Word32]
digest bs = foldl' block h0 (chunks (padMessage bs))
  where
    h0 = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
    chunks [] = []
    chunks xs = let (a, b) = splitAt 64 xs in a : chunks b

block :: [Word32] -> [Word8] -> [Word32]
block hs chunk = zipWith (+) hs (foldl' round' hs [0 .. 63])
  where
    w0 = [be32 (take 4 (drop (4 * i) chunk)) | i <- [0 .. 15]]
    ws = foldl' (\acc _ -> acc ++ [next acc]) w0 [16 .. 63 :: Int]
    next w =
      let s0 = rotateR (w !! (-15 + length w)) 7 `xor` rotateR (w !! (-15 + length w)) 18 `xor` shiftR (w !! (-15 + length w)) 3
          s1 = rotateR (w !! (-2 + length w)) 17 `xor` rotateR (w !! (-2 + length w)) 19 `xor` shiftR (w !! (-2 + length w)) 10
       in w !! (-16 + length w) + s0 + w !! (-7 + length w) + s1
    round' [a, b, c, d, e, f, g, h] i =
      let s1 = rotateR e 6 `xor` rotateR e 11 `xor` rotateR e 25
          ch = (e .&. f) `xor` (complement e .&. g)
          t1 = h + s1 + ch + (k256 !! i) + (ws !! i)
          s0 = rotateR a 2 `xor` rotateR a 13 `xor` rotateR a 22
          maj = (a .&. b) `xor` (a .&. c) `xor` (b .&. c)
          t2 = s0 + maj
       in [t1 + t2, a, b, c, d + t1, e, f, g]
    round' st _ = st
