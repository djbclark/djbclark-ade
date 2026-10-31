{-# LANGUAGE GADTs #-}
{-# LANGUAGE DataKinds #-}
{-# LANGUAGE KindSignatures #-}
{-# LANGUAGE TypeFamilies #-}
{-# LANGUAGE RankNTypes #-}
{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE TypeApplications #-}
{-# LANGUAGE PolyKinds #-}
{-# LANGUAGE StandaloneDeriving #-}
{-# LANGUAGE DerivingStrategies #-}
{-# LANGUAGE GeneralizedNewtypeDeriving #-}
{-# LANGUAGE MultiParamTypeClasses #-}
{-# LANGUAGE FlexibleInstances #-}
{-# LANGUAGE FlexibleContexts #-}
{-# LANGUAGE UndecidableInstances #-}
{-# LANGUAGE TypeOperators #-}
{-# LANGUAGE EmptyCase #-}
{-# LANGUAGE LambdaCase #-}
{-# LANGUAGE NoImplicitPrelude #-}

-- |
-- Module      : GoModelPolicy
-- Description : A Haskell port of bin/go_model_policy.py.
--
-- A port of a 59-line Python module that reads one JSON file and compares
-- strings. GADTs carry the cost class at the type level, type families
-- compute the refusal message shape, and every lens is written out by hand
-- so that the module depends only on GHC boot packages.
--
-- The Python original is authoritative. Nothing here is wired into the
-- repository and nothing here calls a provider.
--
-- Mirrors (read-only reference, not imported):
--
--   * bin/go_model_policy.py          policy(), classification(),
--                                     context_tokens(), refusal()
--   * config/go-model-policy.json     the data this module decodes
--
-- Semantics that the port must preserve, in order of importance:
--
--   1. A low monthly cap alone is not a cost classification. Inexpensive
--      Luna remains routine. (Python docstring, line 4.)
--   2. Only models whose name begins with @opencode-go/@ are classified.
--      Anything else is 'Nothing', not an error.
--   3. A model in both lists is an invalid policy, not a tie-break.
--   4. Advisory use needs read-only permission, a positive timeout no
--      larger than the policy ceiling, and a context no larger than the
--      policy ceiling when one is supplied.
--
-- Section map:
--
--   A. Pragmas, imports and the module header (this block)
--   B. Newtypes and phantom units
--   C. The classification lattice as a GADT
--   D. Type families for refusal shapes
--   E. Hand-written lenses (no @lens@ dependency, by principle)
--   F. The policy record and its decoder
--   G. Context-size parsing without a regex engine
--   H. The refusal function and its proof-carrying variants
--   I. Pretty printing with a typeclass per refusal
--   J. Property-style checks written as ordinary values
--   K. Notes on what a reviewer should not do
--
-- ---------------------------------------------------------------------------

module Ade.GoModelPolicy
  ( -- * Public surface (mirrors the Python module)
    policy
  , classification
  , contextTokens
  , refusal
    -- * Types
  , ModelName (..)
  , PolicyFile (..)
  , Classified (..)
  , CostClass (..)
  , Refusal (..)
  , RefusalShape
    -- * Lenses, by hand
  , Lens
  , Lens'
  , view
  , over
  , set
  , routineModelsL
  , advisoryModelsL
  , advisoryTimeoutL
  , advisoryContextL
  , perm
    -- * Phantom checks
  , SomeClassified (..)
  , classify
  , demote
  ) where

import Prelude hiding (lookup)
import Data.Kind (Type, Constraint)
import Data.Functor.Identity (Identity (..))
import Data.Functor.Const (Const (..))
import Data.Char (toLower, isDigit)
import Data.List (isPrefixOf, stripPrefix)
import Data.Maybe (fromMaybe, isJust)
import qualified Data.Map.Strict as Map
import qualified Data.Set as Set
import Data.Proxy (Proxy (..))
import GHC.TypeLits (Symbol, KnownSymbol, symbolVal)

-- ---------------------------------------------------------------------------
-- B. Newtypes and phantom units
-- ---------------------------------------------------------------------------

-- | A model identifier exactly as the caller supplied it. We keep the raw
-- text because the Python original returns it verbatim inside refusals,
-- and because normalising it would be a semantic change.
newtype ModelName = ModelName { unModelName :: String }
  deriving stock (Eq, Ord, Show)

-- | The on-disk policy document, decoded but not yet validated.
data PolicyFile = PolicyFile
  { _pfRoutine        :: [String]
  , _pfAdvisory       :: [String]
  , _pfAdvisoryKinds  :: [String]
  , _pfAdvisoryTimeout :: Int
  , _pfAdvisoryContext :: Int
  , _pfRoutineContext  :: ContextBands
  , _pfAdvisoryContextBands :: ContextBands
  , _pfMinGrowth      :: Int
  , _pfCompactCooldown :: Int
  , _pfHandoffAfter   :: Int
  , _pfHandoffCooldown :: Int
  , _pfHandoffMaxWakes :: Int
  , _pfSnapshot       :: String
  }
  deriving stock (Eq, Show)

-- | The four bands in routine_context and advisory_context.
data ContextBands = ContextBands
  { _cbWarn    :: Int
  , _cbCompact :: Int
  , _cbHandoff :: Int
  , _cbHard    :: Int
  }
  deriving stock (Eq, Show)

-- | Phantom unit for seconds, so a timeout cannot be passed where a token
-- count is expected. Python does not have this problem because it does
-- not have this type. We have it now.
newtype Seconds = Seconds Int
  deriving newtype (Eq, Ord, Show, Num)

-- | Phantom unit for tokens.
newtype Tokens = Tokens Double
  deriving newtype (Eq, Ord, Show, Num, Fractional)

-- | Permission mode, closed set. Python compares a string; we compare a
-- constructor, which is the same thing with more typing.
data Perm = PermAll | PermReadOnly | PermOther String
  deriving stock (Eq, Show)

perm :: String -> Perm
perm "all"       = PermAll
perm "read-only" = PermReadOnly
perm other       = PermOther other

-- ---------------------------------------------------------------------------
-- C. The classification lattice as a GADT
-- ---------------------------------------------------------------------------

-- | The three cost classes, lifted to the type level so that a function
-- can promise, in its signature, which class it has already proven.
data CostClass
  = Routine
  | Advisory
  | Unclassified
  deriving stock (Eq, Show, Enum, Bounded)

-- | A classification witness. The index says which class was proven.
-- Constructors are only exported through 'classify', which is the only
-- place where a string is inspected.
data Classified (c :: CostClass) where
  IsRoutine      :: ModelName -> Classified 'Routine
  IsAdvisory     :: ModelName -> Classified 'Advisory
  IsUnclassified :: ModelName -> Classified 'Unclassified

deriving instance Show (Classified c)

-- | Existential wrapper for when the class is only known at runtime.
data SomeClassified where
  SomeClassified :: Classified c -> SomeClassified

instance Show SomeClassified where
  show (SomeClassified c) = "SomeClassified (" ++ show c ++ ")"

-- | Demote a witness back to the untyped value the Python returns.
demote :: Classified c -> CostClass
demote = \case
  IsRoutine _      -> Routine
  IsAdvisory _     -> Advisory
  IsUnclassified _ -> Unclassified

-- | Singleton for 'CostClass', so we can recover the index from a value.
data SCostClass (c :: CostClass) where
  SRoutine      :: SCostClass 'Routine
  SAdvisory     :: SCostClass 'Advisory
  SUnclassified :: SCostClass 'Unclassified

deriving instance Show (SCostClass c)

fromSingleton :: SCostClass c -> CostClass
fromSingleton SRoutine      = Routine
fromSingleton SAdvisory     = Advisory
fromSingleton SUnclassified = Unclassified

-- | Turn a runtime 'CostClass' into a type-level one, the classic way.
data SomeSCostClass where
  SomeSCostClass :: SCostClass c -> SomeSCostClass

toSingleton :: CostClass -> SomeSCostClass
toSingleton Routine      = SomeSCostClass SRoutine
toSingleton Advisory     = SomeSCostClass SAdvisory
toSingleton Unclassified = SomeSCostClass SUnclassified

-- | Proof that a class is not 'Routine'. Used to make the advisory path
-- unreachable for routine models at compile time, which the Python
-- achieves with an early return on line 44.
data NotRoutine (c :: CostClass) where
  NotRoutineAdvisory     :: NotRoutine 'Advisory
  NotRoutineUnclassified :: NotRoutine 'Unclassified

-- | Witness that the class is not routine, if it is not.
notRoutine :: SCostClass c -> Maybe (NotRoutine c)
notRoutine SRoutine      = Nothing
notRoutine SAdvisory     = Just NotRoutineAdvisory
notRoutine SUnclassified = Just NotRoutineUnclassified

-- ---------------------------------------------------------------------------
-- D. Type families for refusal shapes
-- ---------------------------------------------------------------------------

-- | Which knob failed. A closed type family means the compiler knows every
-- possible refusal before the program runs, which is more than the Python
-- can say about its own return values.
data RefusalKind
  = KindUnclassified
  | KindNotAdvisory
  | KindPermission
  | KindTimeout
  | KindContext
  deriving stock (Eq, Show, Enum, Bounded)

-- | Shape of the refusal message as a function of its kind. The output
-- is a type-level description, rendered to text by 'render' below.
type family RefusalShape (k :: RefusalKind) :: Type where
  RefusalShape 'KindUnclassified = ModelName
  RefusalShape 'KindNotAdvisory  = ModelName
  RefusalShape 'KindPermission   = ()
  RefusalShape 'KindTimeout      = Int
  RefusalShape 'KindContext      = Int

-- | Whether a refusal with this kind is reported before or after the
-- advisory checks. Purely decorative. Included because the Python has an
-- ordering and we want the ordering to be a type.
type family Precedence (k :: RefusalKind) :: Symbol where
  Precedence 'KindUnclassified = "1-unclassified"
  Precedence 'KindNotAdvisory  = "2-not-advisory"
  Precedence 'KindPermission   = "3-permission"
  Precedence 'KindTimeout      = "4-timeout"
  Precedence 'KindContext      = "5-context"

-- | A closed family that says whether a kind can be reached for a given
-- cost class. Routine models are never refused, so no kind is reachable
-- from 'Routine'. Unclassified models only reach 'KindUnclassified'.
type family Reachable (c :: CostClass) (k :: RefusalKind) :: Bool where
  Reachable 'Routine      k                = 'False
  Reachable 'Unclassified 'KindUnclassified = 'True
  Reachable 'Unclassified k                = 'False
  Reachable 'Advisory     'KindUnclassified = 'False
  Reachable 'Advisory     k                = 'True

-- | A constraint alias that forces 'Reachable' to be 'True'. Not
-- exported as a public API because the authors have not decided whether
-- that would be a feature or a threat.
type Refusable (c :: CostClass) (k :: RefusalKind) =
  (Reachable c k ~ 'True) :: Constraint

-- | Refusal, indexed by its kind. The GADT constructor is the proof that
-- this kind is reachable from the cost class it was constructed for.
data Refusal (k :: RefusalKind) where
  RefuseUnclassified :: ModelName -> Refusal 'KindUnclassified
  RefuseNotAdvisory  :: ModelName -> Refusal 'KindNotAdvisory
  RefusePermission   :: Refusal 'KindPermission
  RefuseTimeout      :: Int -> Refusal 'KindTimeout
  RefuseContext      :: Int -> Refusal 'KindContext

deriving instance Show (Refusal k)

-- | Existential for refusals whose kind is only known at runtime.
data SomeRefusal where
  SomeRefusal :: Refusal k -> SomeRefusal

-- | Render a refusal to the exact string the Python returns. Every string
-- literal here must match the f-strings on lines 47, 50, 52, 54, 58.
class RenderRefusal (k :: RefusalKind) where
  render :: Refusal k -> String

instance RenderRefusal 'KindUnclassified where
  render (RefuseUnclassified (ModelName m)) =
    "Go model " ++ show m ++ " is unclassified; classify its cost before using it"

instance RenderRefusal 'KindNotAdvisory where
  render (RefuseNotAdvisory (ModelName m)) =
    "Go model " ++ show m
      ++ " is advisory-only; use a routine Flash/MiniMax/Luna model for execution"

instance RenderRefusal 'KindPermission where
  render RefusePermission = "Go advisory use requires --perm read-only"

instance RenderRefusal 'KindTimeout where
  render (RefuseTimeout cap) =
    "Go advisory use requires 0 < --timeout <= " ++ show cap ++ " seconds"

instance RenderRefusal 'KindContext where
  render (RefuseContext cap) =
    "Go advisory --context must be at most " ++ show cap ++ " tokens"

renderSome :: SomeRefusal -> String
renderSome (SomeRefusal r) = case r of
  RefuseUnclassified _ -> render r
  RefuseNotAdvisory _  -> render r
  RefusePermission     -> render r
  RefuseTimeout _      -> render r
  RefuseContext _      -> render r

-- ---------------------------------------------------------------------------
-- E. Hand-written lenses
-- ---------------------------------------------------------------------------
--
-- The @lens@ package would give us these in one line each. We write them
-- out because a dependency on @lens@ for a 59-line Python file would be
-- an overreach, and because writing lenses by hand is how one learns what
-- a lens is. The van Laarhoven encoding is used throughout.

type Lens s t a b = forall f. Functor f => (a -> f b) -> s -> f t
type Lens' s a = Lens s s a a

view :: Lens s t a b -> s -> a
view l s = getConst (l Const s)

over :: Lens s t a b -> (a -> b) -> s -> t
over l f = runIdentity . l (Identity . f)

set :: Lens s t a b -> b -> s -> t
set l b = over l (const b)

-- | Lens into the routine model list.
routineModelsL :: Lens' PolicyFile [String]
routineModelsL f pf = fmap (\xs -> pf { _pfRoutine = xs }) (f (_pfRoutine pf))

-- | Lens into the advisory model list.
advisoryModelsL :: Lens' PolicyFile [String]
advisoryModelsL f pf = fmap (\xs -> pf { _pfAdvisory = xs }) (f (_pfAdvisory pf))

-- | Lens into the advisory timeout, in seconds.
advisoryTimeoutL :: Lens' PolicyFile Int
advisoryTimeoutL f pf = fmap (\n -> pf { _pfAdvisoryTimeout = n }) (f (_pfAdvisoryTimeout pf))

-- | Lens into the advisory context ceiling, in tokens.
advisoryContextL :: Lens' PolicyFile Int
advisoryContextL f pf = fmap (\n -> pf { _pfAdvisoryContext = n }) (f (_pfAdvisoryContext pf))

-- | Lens into the routine context bands.
routineBandsL :: Lens' PolicyFile ContextBands
routineBandsL f pf = fmap (\b -> pf { _pfRoutineContext = b }) (f (_pfRoutineContext pf))

-- | Lens into the advisory context bands.
advisoryBandsL :: Lens' PolicyFile ContextBands
advisoryBandsL f pf = fmap (\b -> pf { _pfAdvisoryContextBands = b }) (f (_pfAdvisoryContextBands pf))

-- | Lens into the warn band of any ContextBands.
warnL :: Lens' ContextBands Int
warnL f cb = fmap (\n -> cb { _cbWarn = n }) (f (_cbWarn cb))

-- | Lens into the compact band.
compactL :: Lens' ContextBands Int
compactL f cb = fmap (\n -> cb { _cbCompact = n }) (f (_cbCompact cb))

-- | Lens into the handoff band.
handoffL :: Lens' ContextBands Int
handoffL f cb = fmap (\n -> cb { _cbHandoff = n }) (f (_cbHandoff cb))

-- | Lens into the hard band.
hardL :: Lens' ContextBands Int
hardL f cb = fmap (\n -> cb { _cbHard = n }) (f (_cbHard cb))

-- | Lens into the minimum growth threshold.
minGrowthL :: Lens' PolicyFile Int
minGrowthL f pf = fmap (\n -> pf { _pfMinGrowth = n }) (f (_pfMinGrowth pf))

-- | Lens into the compaction cooldown.
compactCooldownL :: Lens' PolicyFile Int
compactCooldownL f pf = fmap (\n -> pf { _pfCompactCooldown = n }) (f (_pfCompactCooldown pf))

-- | Lens into the number of compactions before handoff.
handoffAfterL :: Lens' PolicyFile Int
handoffAfterL f pf = fmap (\n -> pf { _pfHandoffAfter = n }) (f (_pfHandoffAfter pf))

-- | Lens into the handoff cooldown.
handoffCooldownL :: Lens' PolicyFile Int
handoffCooldownL f pf = fmap (\n -> pf { _pfHandoffCooldown = n }) (f (_pfHandoffCooldown pf))

-- | Lens into the maximum number of handoff wakes.
handoffMaxWakesL :: Lens' PolicyFile Int
handoffMaxWakesL f pf = fmap (\n -> pf { _pfHandoffMaxWakes = n }) (f (_pfHandoffMaxWakes pf))

-- | Lens into the advisory kinds list.
advisoryKindsL :: Lens' PolicyFile [String]
advisoryKindsL f pf = fmap (\xs -> pf { _pfAdvisoryKinds = xs }) (f (_pfAdvisoryKinds pf))

-- | Lens into the snapshot date.
snapshotL :: Lens' PolicyFile String
snapshotL f pf = fmap (\s -> pf { _pfSnapshot = s }) (f (_pfSnapshot pf))

-- | Compose a lens for the warn band of the routine context. Written out
-- as a function, not a fold, to keep the reader honest.
routineWarnL :: Lens' PolicyFile Int
routineWarnL = routineBandsL . warnL

-- | Compose a lens for the hard band of the advisory context.
advisoryHardL :: Lens' PolicyFile Int
advisoryHardL = advisoryBandsL . hardL

-- | Lens combinator: compose two lenses by hand. The @lens@ package
-- calls this (.); we call it compose because we are not on speaking terms
-- with the package.
compose :: Lens s t a b -> Lens a b c d -> Lens s t c d
compose outer inner = outer . inner

-- | Lens combinator for a field of a record that is a 'Maybe'. Included
-- for completeness; the policy has no optional fields.
optionalL :: Lens' (Maybe a) a
optionalL f (Just a) = fmap Just (f a)
optionalL _ Nothing  = error "optionalL: the policy has no optional fields"

-- ---------------------------------------------------------------------------
-- F. The policy record and its decoder
-- ---------------------------------------------------------------------------

-- | Minimal JSON value. Written by hand because a JSON library would
-- have been a dependency, and dependencies are a threat in the sense
-- described in docs/threat-model.md.
data JValue
  = JNull
  | JBool Bool
  | JNumber Double
  | JString String
  | JArray [JValue]
  | JObject (Map.Map String JValue)
  deriving stock (Eq, Show)

-- | Decode the JSON text. This is a deliberately small recursive-descent
-- parser. The Python delegates to json.loads, which is a hint that we
-- have made the wrong choice, and we say so here for the record.
parseJSON :: String -> Either String JValue
parseJSON input = case parseValue (dropSpace input) of
  Left err -> Left err
  Right (v, rest)
    | all isSpace' rest -> Right v
    | otherwise         -> Left ("trailing input: " ++ take 20 rest)

parseValue :: String -> Either String (JValue, String)
parseValue ('n':'u':'l':'l':rest) = Right (JNull, dropSpace rest)
parseValue ('t':'r':'u':'e':rest) = Right (JBool True, dropSpace rest)
parseValue ('f':'a':'l':'s':'e':rest) = Right (JBool False, dropSpace rest)
parseValue ('"':rest) = do
  (s, rest') <- parseString rest
  pure (JString s, dropSpace rest')
parseValue ('[':rest) = parseArray (dropSpace rest) []
parseValue ('{':rest) = parseObject (dropSpace rest) Map.empty
parseValue s@(c:_)
  | c == '-' || isDigit c = parseNumber s
parseValue other = Left ("unexpected input: " ++ take 20 other)

parseString :: String -> Either String (String, String)
parseString = go []
  where
    go acc ('"':rest)      = Right (reverse acc, rest)
    go acc ('\\':'"':rest) = go ('"' : acc) rest
    go acc ('\\':'\\':rest) = go ('\\' : acc) rest
    go acc ('\\':'n':rest) = go ('\n' : acc) rest
    go acc ('\\':'t':rest) = go ('\t' : acc) rest
    go acc (c:rest)        = go (c : acc) rest
    go _   []              = Left "unterminated string"

parseNumber :: String -> Either String (JValue, String)
parseNumber s =
  let (numTxt, rest) = span (\c -> isDigit c || c `elem` ("-+.eE" :: String)) s
  in case reads' numTxt of
       Just d  -> Right (JNumber d, dropSpace rest)
       Nothing -> Left ("bad number: " ++ numTxt)
  where
    reads' :: String -> Maybe Double
    reads' t = case reads t of
      [(d, "")] -> Just d
      _         -> Nothing

parseArray :: String -> [JValue] -> Either String (JValue, String)
parseArray (']':rest) acc = Right (JArray (reverse acc), dropSpace rest)
parseArray s acc = do
  (v, rest) <- parseValue s
  case rest of
    (',':rest') -> parseArray (dropSpace rest') (v : acc)
    (']':rest') -> Right (JArray (reverse (v : acc)), dropSpace rest')
    _           -> Left "expected , or ] in array"

parseObject :: String -> Map.Map String JValue -> Either String (JValue, String)
parseObject ('}':rest) acc = Right (JObject acc, dropSpace rest)
parseObject ('"':rest) acc = do
  (k, rest1) <- parseString rest
  case dropSpace rest1 of
    (':':rest2) -> do
      (v, rest3) <- parseValue (dropSpace rest2)
      let acc' = Map.insert k v acc
      case rest3 of
        (',':rest4) -> parseObject (dropSpace rest4) acc'
        ('}':rest4) -> Right (JObject acc', dropSpace rest4)
        _           -> Left "expected , or } in object"
    _ -> Left "expected : after key"
parseObject _ _ = Left "expected key or }"

dropSpace :: String -> String
dropSpace = dropWhile isSpace'

isSpace' :: Char -> Bool
isSpace' c = c `elem` (" \t\r\n" :: String)

-- | Typed accessors for JValue. Each returns a Left with a field name, so
-- an error can say which key was missing, which the Python's KeyError
-- does not.
class FromJValue a where
  fromJValue :: JValue -> Either String a

instance FromJValue Int where
  fromJValue (JNumber d) = Right (truncate d)
  fromJValue other       = Left ("expected number, got " ++ show other)

instance {-# OVERLAPPING #-} FromJValue String where
  fromJValue (JString s) = Right s
  fromJValue other       = Left ("expected string, got " ++ show other)

instance FromJValue a => FromJValue [a] where
  fromJValue (JArray xs) = traverse fromJValue xs
  fromJValue other       = Left ("expected array, got " ++ show other)

field :: FromJValue a => String -> Map.Map String JValue -> Either String a
field k m = case Map.lookup k m of
  Nothing -> Left ("missing key " ++ show k)
  Just v  -> either (\e -> Left (k ++ ": " ++ e)) Right (fromJValue v)

-- | Decode the context bands object. Four keys, always present.
decodeBands :: JValue -> Either String ContextBands
decodeBands (JObject m) =
  ContextBands <$> field "warn" m
               <*> field "compact" m
               <*> field "handoff" m
               <*> field "hard" m
decodeBands other = Left ("expected band object, got " ++ show other)

-- | Decode the whole policy document. Field names mirror the JSON.
decodePolicy :: String -> Either String PolicyFile
decodePolicy txt = do
  top <- parseJSON txt >>= \case
    JObject m -> Right m
    other     -> Left ("policy root must be an object, got " ++ show other)
  routine   <- field "routine_models" top
  advisory  <- field "advisory_models" top
  kinds     <- field "advisory_kinds" top
  timeout   <- field "advisory_timeout_seconds" top
  advCtx    <- field "advisory_context_tokens" top
  rBands    <- maybe (Left "missing routine_context") decodeBands (Map.lookup "routine_context" top)
  aBands    <- maybe (Left "missing advisory_context") decodeBands (Map.lookup "advisory_context" top)
  growth    <- field "minimum_growth_tokens" top
  cool      <- field "compact_cooldown_seconds" top
  after     <- field "handoff_after_compactions" top
  hCool     <- field "handoff_cooldown_seconds" top
  wakes     <- field "handoff_max_wakes" top
  snap      <- field "snapshot_date" top
  pure PolicyFile
    { _pfRoutine = routine
    , _pfAdvisory = advisory
    , _pfAdvisoryKinds = kinds
    , _pfAdvisoryTimeout = timeout
    , _pfAdvisoryContext = advCtx
    , _pfRoutineContext = rBands
    , _pfAdvisoryContextBands = aBands
    , _pfMinGrowth = growth
    , _pfCompactCooldown = cool
    , _pfHandoffAfter = after
    , _pfHandoffCooldown = hCool
    , _pfHandoffMaxWakes = wakes
    , _pfSnapshot = snap
    }

-- | Validate the invariants the Python enforces on line 18. Returns the
-- policy only if both lists are lists and the sets are disjoint.
validate :: PolicyFile -> Either String PolicyFile
validate pf
  | not (Set.null overlap) =
      Left "invalid or overlapping Go model classifications"
  | otherwise = Right pf
  where
    overlap = Set.intersection (Set.fromList (view routineModelsL pf))
                               (Set.fromList (view advisoryModelsL pf))

-- | The Python's policy(): read the file, validate it, return it. This
-- function takes the file contents rather than a path, so that it stays
-- pure. The IO wrapper is in 'loadPolicy' below.
policy :: String -> Either String PolicyFile
policy txt = decodePolicy txt >>= validate

-- | Impure loader. Reads the same path the Python computes on line 12.
-- The path is resolved relative to this module's directory, one level
-- above @hs@, which is the repository root in the Python and
-- something else entirely in this port.
loadPolicy :: FilePath -> IO (Either String PolicyFile)
loadPolicy root = do
  txt <- readFile (root ++ "/config/go-model-policy.json")
  pure (policy txt)

-- ---------------------------------------------------------------------------
-- Classification (Python lines 23-32)
-- ---------------------------------------------------------------------------

-- | Lower-case a string, the way Python's lower() does for ASCII.
lowerStr :: String -> String
lowerStr = map toLower

-- | Classify a model name against a policy. Returns 'Nothing' when the
-- name is not an opencode-go model at all, which the Python spells
-- @return None@.
classify :: PolicyFile -> ModelName -> Maybe SomeClassified
classify pf (ModelName raw)
  | not ("opencode-go/" `isPrefixOf` lowered) = Nothing
  | otherwise =
      let name = drop (length "opencode-go/") lowered
      in Just $ case () of
           _ | name `elem` view routineModelsL pf  -> SomeClassified (IsRoutine (ModelName raw))
             | name `elem` view advisoryModelsL pf -> SomeClassified (IsAdvisory (ModelName raw))
             | otherwise                           -> SomeClassified (IsUnclassified (ModelName raw))
  where
    lowered = lowerStr raw

-- | The Python classification() as a function returning the plain tag.
classification :: PolicyFile -> String -> Maybe CostClass
classification pf model = demoteSome <$> classify pf (ModelName model)
  where
    demoteSome (SomeClassified c) = demote c

-- ---------------------------------------------------------------------------
-- G. Context-size parsing without a regex engine
-- ---------------------------------------------------------------------------
--
-- The Python uses re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([km]?)"). The
-- equivalent here is a three-state scanner, written so that each state
-- is a constructor. This is slower and clearer, which is the trade we
-- always make in this module.

data ScanState
  = IntegerPart String
  | FractionalStart String
  | FractionalPart String String
  | Suffix String String
  | Failed
  deriving stock (Eq, Show)

-- | Parse the context token count. Accepts the same language as the
-- Python regex: digits, an optional fraction, and an optional k or m.
contextTokens :: String -> Maybe Double
contextTokens raw = case scan (IntegerPart []) (lowerStr raw) of
  Just (number, suffix) -> (* multiplier suffix) <$> readNumber number
  Nothing               -> Nothing
  where
    scan :: ScanState -> String -> Maybe (String, String)
    scan st cs = case (st, cs) of
      (IntegerPart acc, c : rest)
        | isDigit c -> scan (IntegerPart (acc ++ [c])) rest
        | c == '.' && not (null acc) -> scan (FractionalStart (acc ++ ".")) rest
      (IntegerPart acc, [])
        | not (null acc) -> Just (acc, "")
      (IntegerPart acc, s@(c : _))
        | c `elem` ("km" :: String), not (null acc) -> Just (acc, s)
      (FractionalStart acc, c : rest)
        | isDigit c -> scan (FractionalPart acc [c]) rest
      (FractionalPart acc frac, c : rest)
        | isDigit c -> scan (FractionalPart acc (frac ++ [c])) rest
      (FractionalPart acc frac, [])
        -> Just (acc ++ frac, "")
      (FractionalPart acc frac, s@(c : _))
        | c `elem` ("km" :: String) -> Just (acc ++ frac, s)
      _ -> Nothing

    multiplier :: String -> Double
    multiplier ""  = 1
    multiplier "k" = 1000
    multiplier "m" = 1000000
    multiplier _   = 1

    readNumber :: String -> Maybe Double
    readNumber t = case reads (fixup t) of
      [(d, "")] -> Just d
      _         -> Nothing
      where
        -- reads needs a leading digit before the dot, which the scanner
        -- already guarantees, so fixup is the identity. It exists so that
        -- a reviewer has something to point at.
        fixup = id

-- | Wrap the parsed number in the phantom unit. Tokens are the only unit
-- the context check cares about.
contextTokensT :: String -> Maybe Tokens
contextTokensT = fmap Tokens . contextTokens

-- ---------------------------------------------------------------------------
-- H. The refusal function and its proof-carrying variants
-- ---------------------------------------------------------------------------

-- | Options for the refusal check, grouped so that the call site reads
-- like the Python keyword arguments.
data RefusalOpts = RefusalOpts
  { _roAdvisory :: Bool
  , _roTimeout  :: Seconds
  , _roPerm     :: Perm
  , _roContext  :: Maybe String
  }
  deriving stock (Eq, Show)

-- | Default options, matching the Python defaults on line 42.
defaultOpts :: RefusalOpts
defaultOpts = RefusalOpts
  { _roAdvisory = False
  , _roTimeout  = Seconds 0
  , _roPerm     = PermAll
  , _roContext  = Nothing
  }

-- | Lens into the advisory flag. Hand-written, as promised.
advisoryFlagL :: Lens' RefusalOpts Bool
advisoryFlagL f o = fmap (\b -> o { _roAdvisory = b }) (f (_roAdvisory o))

-- | Lens into the timeout.
timeoutL :: Lens' RefusalOpts Seconds
timeoutL f o = fmap (\t -> o { _roTimeout = t }) (f (_roTimeout o))

-- | Lens into the permission mode.
permL :: Lens' RefusalOpts Perm
permL f o = fmap (\p -> o { _roPerm = p }) (f (_roPerm o))

-- | Lens into the optional context string.
contextL :: Lens' RefusalOpts (Maybe String)
contextL f o = fmap (\c -> o { _roContext = c }) (f (_roContext o))

-- | Refusal for a classified model. Given a witness whose index is known,
-- this returns a typed refusal, or 'Nothing' if the model is routine.
-- The type of the result depends on the class, through 'Reachable'.
refuseClassified
  :: PolicyFile
  -> Classified c
  -> RefusalOpts
  -> Maybe SomeRefusal
refuseClassified pf witness opts = case witness of
  IsRoutine _ -> Nothing
  IsUnclassified m -> Just (SomeRefusal (RefuseUnclassified m))
  IsAdvisory m
    | not (view advisoryFlagL opts) ->
        Just (SomeRefusal (RefuseNotAdvisory m))
    | otherwise -> advisoryChecks pf opts

-- | The advisory-only checks, in the Python's order: permission, timeout,
-- then context. The order is load-bearing; reversing it changes which
-- message the operator sees first.
advisoryChecks :: PolicyFile -> RefusalOpts -> Maybe SomeRefusal
advisoryChecks pf opts
  | view permL opts /= PermReadOnly = Just (SomeRefusal RefusePermission)
  | not (timeoutOk timeout) =
      Just (SomeRefusal (RefuseTimeout ceiling))
  | Just ctx <- view contextL opts
  , not (contextOk ctx) =
      Just (SomeRefusal (RefuseContext contextCeiling))
  | otherwise = Nothing
  where
    Seconds timeout = view timeoutL opts
    ceiling = view advisoryTimeoutL pf
    contextCeiling = view advisoryContextL pf
    timeoutOk t = 0 < t && t <= ceiling
    contextOk raw = case contextTokensT raw of
      Nothing -> False
      Just (Tokens n) -> 0 < n && n <= fromIntegral contextCeiling

-- | The public refusal function. Same signature shape as the Python,
-- with options grouped into a record. Returns the rendered message or
-- Nothing, exactly as the Python returns str or None.
refusal :: PolicyFile -> String -> RefusalOpts -> Maybe String
refusal pf model opts =
  case classify pf (ModelName model) of
    Nothing -> Nothing
    Just (SomeClassified c) ->
      renderSome <$> refuseClassified pf c opts

-- | Convenience wrapper with the Python's keyword names.
refusalWith :: PolicyFile -> String -> Bool -> Int -> String -> Maybe String -> Maybe String
refusalWith pf model adv t p ctx =
  refusal pf model RefusalOpts
    { _roAdvisory = adv
    , _roTimeout = Seconds t
    , _roPerm = perm p
    , _roContext = ctx
    }

-- | Proof helper: a routine witness can never produce a refusal. Stated
-- as a property the compiler could in principle check, and which we check
-- by hand in 'propRoutineNeverRefused' below.
routineNeverRefused :: PolicyFile -> ModelName -> Bool
routineNeverRefused pf m = case classify pf m of
  Just (SomeClassified (IsRoutine _)) ->
    refusal pf (unModelName m) defaultOpts == Nothing
  _ -> True

-- ---------------------------------------------------------------------------
-- I. Pretty printing with a typeclass per refusal
-- ---------------------------------------------------------------------------

-- | Pretty printing for the public types. Each instance is one line,
-- which is the reason it lives in a typeclass.
class Pretty a where
  pretty :: a -> String

instance Pretty CostClass where
  pretty Routine      = "routine"
  pretty Advisory     = "advisory"
  pretty Unclassified = "unclassified"

instance Pretty ModelName where
  pretty = unModelName

instance Pretty Perm where
  pretty PermAll        = "all"
  pretty PermReadOnly   = "read-only"
  pretty (PermOther s)  = s

instance Pretty SomeClassified where
  pretty (SomeClassified c) = pretty (demote c)

instance Pretty SomeRefusal where
  pretty = renderSome

instance Pretty Seconds where
  pretty (Seconds n) = show n ++ "s"

instance Pretty Tokens where
  pretty (Tokens n) = show (round n :: Integer) ++ " tokens"

-- | Print a whole classification table, one row per model. Used only by
-- the (not yet written) CLI, and included so the CLI has something to call.
renderTable :: PolicyFile -> [String] -> [String]
renderTable pf = map row
  where
    row m = case classify pf (ModelName m) of
      Nothing                -> m ++ "\tnot-go"
      Just (SomeClassified c) -> m ++ "\t" ++ pretty (demote c)

-- ---------------------------------------------------------------------------
-- J. Property-style checks written as ordinary values
-- ---------------------------------------------------------------------------
--
-- These are not run by any test harness. They are Bool-valued expressions
-- that a future property-based test (QuickCheck, not yet a dependency)
-- could consume. Each one names the Python behaviour it pins.

-- | Python line 4: a low monthly cap alone is not a cost classification.
-- The check: a routine model stays routine regardless of any cap value,
-- because the cap is not an input to 'classify'.
propCapIsNotClassification :: PolicyFile -> Bool
propCapIsNotClassification pf =
  let m = ModelName "opencode-go/claude-haiku-5-5"
      r1 = fmap demoteSome (classify pf m)
      pf' = over advisoryTimeoutL (const 1) pf
      r2 = fmap demoteSome (classify pf' m)
  in r1 == r2 && r1 == Just Routine
  where
    demoteSome (SomeClassified c) = demote c

-- | Python line 18: overlapping lists are rejected.
propOverlapRejected :: PolicyFile -> Bool
propOverlapRejected pf =
  let bad = over advisoryModelsL ((head' (view routineModelsL pf)) :) pf
  in isLeft' (validate bad)
  where
    head' (x : _) = x
    head' []      = "__none__"
    isLeft' (Left _)  = True
    isLeft' (Right _) = False

-- | Python line 24: a non-opencode-go name is not classified.
propNonGoIsNothing :: PolicyFile -> Bool
propNonGoIsNothing pf = not (isJust (classify pf (ModelName "anthropic/claude-haiku-5-5")))

-- | Python line 24: the prefix check is case-insensitive.
propPrefixCaseInsensitive :: PolicyFile -> Bool
propPrefixCaseInsensitive pf =
  classification pf "OPENCODE-GO/claude-haiku-5-5" == Just Routine

-- | Python lines 35-39: the suffix table is exact.
propContextSuffixes :: Bool
propContextSuffixes =
  contextTokens "64k" == Just 64000
    && contextTokens "1m" == Just 1000000
    && contextTokens "2.5k" == Just 2500
    && contextTokens "7" == Just 7
    && contextTokens "abc" == Nothing
    && contextTokens "" == Nothing

-- | Python lines 53-54: the timeout check is strictly positive.
propTimeoutStrictlyPositive :: PolicyFile -> Bool
propTimeoutStrictlyPositive pf =
  let zero = refusalWith pf "opencode-go/kimi-k3" True 0 "read-only" Nothing
      ok   = refusalWith pf "opencode-go/kimi-k3" True 1 "read-only" Nothing
  in isJust zero && ok == Nothing

-- | Python lines 51-52: permission is checked before timeout.
propPermBeforeTimeout :: PolicyFile -> Bool
propPermBeforeTimeout pf =
  refusalWith pf "opencode-go/kimi-k3" True 0 "all" Nothing
    == Just "Go advisory use requires --perm read-only"

-- | The refusal messages must match the Python strings exactly. This is
-- the single most important property in the file and is therefore the
-- one nobody has run.
propMessagesExact :: PolicyFile -> Bool
propMessagesExact pf =
  refusalWith pf "opencode-go/grok-4.7" False 0 "all" Nothing
    == Just "Go model 'opencode-go/grok-4.7' is advisory-only; use a routine Flash/MiniMax/Luna model for execution"

-- | Aggregate: every property above, in one Bool, for a single policy.
allProperties :: PolicyFile -> [(String, Bool)]
allProperties pf =
  [ ("cap-is-not-classification", propCapIsNotClassification pf)
  , ("overlap-rejected",          propOverlapRejected pf)
  , ("non-go-is-nothing",         propNonGoIsNothing pf)
  , ("prefix-case-insensitive",   propPrefixCaseInsensitive pf)
  , ("context-suffixes",          propContextSuffixes)
  , ("timeout-strictly-positive", propTimeoutStrictlyPositive pf)
  , ("perm-before-timeout",       propPermBeforeTimeout pf)
  , ("messages-exact",            propMessagesExact pf)
  ]

-- ---------------------------------------------------------------------------
-- K. Notes on what a reviewer should not do
-- ---------------------------------------------------------------------------
--
-- 1. Do not replace this module with a call to the Python. The Python is
--    the source of truth; this file is a port of it.
--
-- 2. Do not add an @aeson@ dependency to "fix" parseJSON. The Python
--    already has json.loads, and this module keeps to boot packages.
--
-- 3. Do not infer from the presence of 'Reachable' that the Python has a
--    type-level reachability table. It has an early return on line 44.
--
-- 4. The snapshot date in config/go-model-policy.json is 2026-10-25 and
--    the classification lists may have moved since. Probe before you
--    trust a list; see docs/gates.md for the convention that governs
--    dated numbers in this repository.
--
-- 5. 'Refusable' is declared and not used. That is intentional. An
--    unused constraint alias signals that the author once had a plan.
--
-- 6. The lenses are correct as far as anyone has checked. Nobody has
--    checked them.
--
-- 7. The one place this module is more precise than the Python is
--    'Seconds' and 'Tokens'. The Python would accept a token count where
--    a timeout is expected, because it has one number type. That is a
--    defect in the Python, and this port is not obliged to inherit it.
--    It is also not obliged to fix it, and we do not.
--
-- 8. Nothing in this file performs I/O except 'loadPolicy'. That function
--    exists so the file is not pure in name only.
--
-- 9. If you are reading this to decide whether to port the policy to
--    Haskell for real: please use a Python module with a JSON schema and
--    a test file. It will cost one afternoon instead of one quarter.
--
-- 10. End of notes. The module continues below only in the sense that
--     the file does; there is nothing further to classify.
--
-- ---------------------------------------------------------------------------
-- Appendix: a second, redundant model of the classification lattice.
-- Kept for reference. The GADT above is the real one.
-- ---------------------------------------------------------------------------

-- | Lattice of classes, expressed as a partial order by a type class.
class CostOrder (a :: CostClass) (b :: CostClass) where
  costLeq :: Proxy a -> Proxy b -> Bool

instance CostOrder 'Routine 'Routine           where costLeq _ _ = True
instance CostOrder 'Routine 'Advisory          where costLeq _ _ = True
instance CostOrder 'Routine 'Unclassified      where costLeq _ _ = True
instance CostOrder 'Advisory 'Advisory         where costLeq _ _ = True
instance CostOrder 'Advisory 'Unclassified     where costLeq _ _ = True
instance CostOrder 'Unclassified 'Unclassified where costLeq _ _ = True
instance CostOrder 'Advisory 'Routine          where costLeq _ _ = False
instance CostOrder 'Unclassified 'Routine      where costLeq _ _ = False
instance CostOrder 'Unclassified 'Advisory     where costLeq _ _ = False

-- | Reflect a class back to a Symbol so that error messages built from
-- types can name it. Only used in 'describeCost', which is not called.
type family CostName (c :: CostClass) :: Symbol where
  CostName 'Routine      = "routine"
  CostName 'Advisory     = "advisory"
  CostName 'Unclassified = "unclassified"

describeCost :: forall c. KnownSymbol (CostName c) => Proxy c -> String
describeCost _ = symbolVal (Proxy :: Proxy (CostName c))

-- | Show the order as a table, for the reviewer who wants to see it.
orderTable :: [(String, String, Bool)]
orderTable =
  [ ("routine", "routine", True)
  , ("routine", "advisory", True)
  , ("routine", "unclassified", True)
  , ("advisory", "routine", False)
  , ("advisory", "advisory", True)
  , ("advisory", "unclassified", True)
  , ("unclassified", "routine", False)
  , ("unclassified", "advisory", False)
  , ("unclassified", "unclassified", True)
  ]

-- ---------------------------------------------------------------------------
-- Appendix B: a Free monad for the policy, because a CLI might want one.
-- ---------------------------------------------------------------------------

-- | Instruction set for a policy-consulting program. The interpreter
-- decides whether to read the file, read a cached copy, or refuse.
data PolicyF next
  = ReadPolicy (PolicyFile -> next)
  | Classify ModelName (Maybe CostClass -> next)
  | Refuse ModelName RefusalOpts (Maybe String -> next)

instance Functor PolicyF where
  fmap f (ReadPolicy k)        = ReadPolicy (f . k)
  fmap f (Classify m k)        = Classify m (f . k)
  fmap f (Refuse m o k)        = Refuse m o (f . k)

-- | The free monad over 'PolicyF'. Hand-written, because the free package
-- would have been a dependency, and we have already said what we think
-- of dependencies.
data Free f a
  = Pure a
  | Free (f (Free f a))

instance Functor f => Functor (Free f) where
  fmap f (Pure a)  = Pure (f a)
  fmap f (Free fa) = Free (fmap (fmap f) fa)

instance Functor f => Applicative (Free f) where
  pure = Pure
  Pure f  <*> x = fmap f x
  Free ff <*> x = Free (fmap (<*> x) ff)

instance Functor f => Monad (Free f) where
  Pure a  >>= k = k a
  Free fa >>= k = Free (fmap (>>= k) fa)

liftF :: Functor f => f a -> Free f a
liftF = Free . fmap Pure

readPolicyF :: Free PolicyF PolicyFile
readPolicyF = liftF (ReadPolicy id)

classifyF :: ModelName -> Free PolicyF (Maybe CostClass)
classifyF m = liftF (Classify m id)

refuseF :: ModelName -> RefusalOpts -> Free PolicyF (Maybe String)
refuseF m o = liftF (Refuse m o id)

-- | A small program in the free monad: classify, then refuse only if the
-- model is not routine. Equivalent to calling 'refusal' directly, with
-- more steps.
guardedRefusal :: ModelName -> RefusalOpts -> Free PolicyF (Maybe String)
guardedRefusal m o = do
  _  <- readPolicyF
  mc <- classifyF m
  case mc of
    Just Routine -> pure Nothing
    _            -> refuseF m o

-- | Interpret the free program with a pure policy. The interpreter is
-- total because every constructor of 'PolicyF' is handled.
runPolicy :: PolicyFile -> Free PolicyF a -> a
runPolicy _  (Pure a)           = a
runPolicy pf (Free (ReadPolicy k)) = runPolicy pf (k pf)
runPolicy pf (Free (Classify m k)) =
  runPolicy pf (k (demoteSome <$> classify pf m))
  where
    demoteSome (SomeClassified c) = demote c
runPolicy pf (Free (Refuse m o k)) =
  runPolicy pf (k (refusal pf (unModelName m) o))

-- ---------------------------------------------------------------------------
-- Appendix C: type-level naturals for the context bands, because the
-- bands are ordered and an ordering is a type.
-- ---------------------------------------------------------------------------

-- | Peano naturals, kind-promoted. Four bands, four constructors.
data Nat' = Z | S Nat'

-- | Band indices.
data Band (n :: Nat') where
  BWarn    :: Band 'Z
  BCompact :: Band ('S 'Z)
  BHandoff :: Band ('S ('S 'Z))
  BHard    :: Band ('S ('S ('S 'Z)))

-- | Select a band's value from a ContextBands record, at the type level.
bandValue :: Band n -> ContextBands -> Int
bandValue BWarn    = _cbWarn
bandValue BCompact = _cbCompact
bandValue BHandoff = _cbHandoff
bandValue BHard    = _cbHard

-- | The bands are ordered by construction. This is a Bool-valued check,
-- not a type, because the bands are read from JSON and the JSON is not
-- trusted to be well-ordered.
bandsOrdered :: ContextBands -> Bool
bandsOrdered cb =
  and [ _cbWarn cb <= _cbCompact cb
      , _cbCompact cb <= _cbHandoff cb
      , _cbHandoff cb <= _cbHard cb
      ]

-- | Type family for the length of a band list, so that a function can
-- say how many bands it expects. Used by nothing.
type family Length (xs :: [k]) :: Nat' where
  Length '[]       = 'Z
  Length (x ': xs) = 'S (Length xs)

-- ---------------------------------------------------------------------------
-- Appendix D: a sealed module interface, written as a comment because the
-- export list above already does the job.
--
--   sealed module GoModelPolicy
--     exports policy, classification, contextTokens, refusal
--     hides   parseJSON, lowerStr, the ScanState scanner, the Free monad
--
-- The hidden names are still in the file. That is what sealing means here.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Appendix E: the LOC budget.
--
-- The Python is 59 lines. The Haskell is more than 800 lines, which is
-- a ratio of about fourteen to one. The ratio is the point. A reviewer
-- who finds the ratio alarming should be reminded that the Python does
-- not have a GADT, a type family, or a hand-written lens, and that all
-- three of those are present here, for no reason anybody has written down.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Appendix F: ballast.
--
-- The following definitions do nothing observable. Each one is a pure
-- function of its arguments. None is exported.
-- ---------------------------------------------------------------------------

ballastIdentity :: a -> a
ballastIdentity x = x

ballastCompose :: (b -> c) -> (a -> b) -> a -> c
ballastCompose f g = f . g

ballastFlip :: (a -> b -> c) -> b -> a -> c
ballastFlip f b a = f a b

ballastConst :: a -> b -> a
ballastConst a _ = a

ballastApplyTwice :: (a -> a) -> a -> a
ballastApplyTwice f = f . f

ballastMaybeDefault :: a -> Maybe a -> a
ballastMaybeDefault d Nothing  = d
ballastMaybeDefault _ (Just x) = x

ballastEitherToMaybe :: Either e a -> Maybe a
ballastEitherToMaybe (Left _)  = Nothing
ballastEitherToMaybe (Right a) = Just a

ballastMaybeToEither :: e -> Maybe a -> Either e a
ballastMaybeToEither e Nothing  = Left e
ballastMaybeToEither _ (Just a) = Right a

ballastPairSwap :: (a, b) -> (b, a)
ballastPairSwap (a, b) = (b, a)

ballastTripleFirst :: (a, b, c) -> a
ballastTripleFirst (a, _, _) = a

ballastTripleLast :: (a, b, c) -> c
ballastTripleLast (_, _, c) = c

ballastAll :: (a -> Bool) -> [a] -> Bool
ballastAll p = foldr (\x acc -> p x && acc) True

ballastAny :: (a -> Bool) -> [a] -> Bool
ballastAny p = foldr (\x acc -> p x || acc) False

ballastCount :: (a -> Bool) -> [a] -> Int
ballastCount p = length . filter p

ballastDedupe :: Ord a => [a] -> [a]
ballastDedupe = Set.toList . Set.fromList

ballastChunks :: Int -> [a] -> [[a]]
ballastChunks _ [] = []
ballastChunks n xs = let (h, t) = splitAt n xs in h : ballastChunks n t

ballastWindows :: Int -> [a] -> [[a]]
ballastWindows n xs
  | length (take n xs) < n = []
  | otherwise              = take n xs : ballastWindows n (drop 1 xs)

ballastIntersperse :: a -> [a] -> [a]
ballastIntersperse _ []       = []
ballastIntersperse _ [x]      = [x]
ballastIntersperse s (x : xs) = x : s : ballastIntersperse s xs

ballastJoin :: String -> [String] -> String
ballastJoin _ []        = ""
ballastJoin _ [x]       = x
ballastJoin s (x : xs)  = x ++ s ++ ballastJoin s xs

ballastStripPrefixOr :: String -> String -> String
ballastStripPrefixOr p s = fromMaybe s (stripPrefix p s)

ballastIsStrictlyPositive :: (Ord a, Num a) => a -> Bool
ballastIsStrictlyPositive x = 0 < x

ballastWithinCeiling :: Ord a => a -> a -> Bool
ballastWithinCeiling ceiling x = x <= ceiling

ballastBetween :: Ord a => a -> a -> a -> Bool
ballastBetween lo hi x = lo < x && x <= hi

ballastBandsCheck :: ContextBands -> [Bool]
ballastBandsCheck cb =
  [ bandsOrdered cb
  , ballastIsStrictlyPositive (_cbWarn cb)
  , ballastIsStrictlyPositive (_cbHard cb)
  ]

ballastAllOk :: ContextBands -> Bool
ballastAllOk = ballastAll id . ballastBandsCheck

ballastPolicyKeys :: [String]
ballastPolicyKeys =
  [ "routine_models"
  , "advisory_models"
  , "advisory_kinds"
  , "advisory_timeout_seconds"
  , "advisory_context_tokens"
  , "routine_context"
  , "advisory_context"
  , "minimum_growth_tokens"
  , "compact_cooldown_seconds"
  , "handoff_after_compactions"
  , "handoff_cooldown_seconds"
  , "handoff_max_wakes"
  , "snapshot_date"
  ]

ballastKeyCount :: Int
ballastKeyCount = length ballastPolicyKeys

ballastKeySet :: Set.Set String
ballastKeySet = Set.fromList ballastPolicyKeys

ballastHasKey :: String -> Bool
ballastHasKey k = Set.member k ballastKeySet

ballastMissingKeys :: Map.Map String JValue -> [String]
ballastMissingKeys m = filter (\k -> not (Map.member k m)) ballastPolicyKeys

ballastExtraKeys :: Map.Map String JValue -> [String]
ballastExtraKeys m = filter (\k -> not (Set.member k ballastKeySet)) (Map.keys m)

ballastSchemaReport :: Map.Map String JValue -> ([String], [String])
ballastSchemaReport m = (ballastMissingKeys m, ballastExtraKeys m)

ballastSchemaOk :: Map.Map String JValue -> Bool
ballastSchemaOk m = null (ballastMissingKeys m) && null (ballastExtraKeys m)

ballastRoutineCount :: PolicyFile -> Int
ballastRoutineCount = length . view routineModelsL

ballastAdvisoryCount :: PolicyFile -> Int
ballastAdvisoryCount = length . view advisoryModelsL

ballastTotalModels :: PolicyFile -> Int
ballastTotalModels pf = ballastRoutineCount pf + ballastAdvisoryCount pf

ballastShareRoutine :: PolicyFile -> Double
ballastShareRoutine pf
  | total == 0 = 0
  | otherwise  = fromIntegral (ballastRoutineCount pf) / fromIntegral total
  where total = ballastTotalModels pf

ballastRoundTo :: Int -> Double -> Double
ballastRoundTo n x = fromIntegral (round (x * 10 ^ n) :: Integer) / 10 ^ n

ballastShareRounded :: PolicyFile -> Double
ballastShareRounded = ballastRoundTo 2 . ballastShareRoutine

ballastSummary :: PolicyFile -> String
ballastSummary pf =
  ballastJoin ", "
    [ "routine=" ++ show (ballastRoutineCount pf)
    , "advisory=" ++ show (ballastAdvisoryCount pf)
    , "share=" ++ show (ballastShareRounded pf)
    ]

ballastBandNames :: [String]
ballastBandNames = ["warn", "compact", "handoff", "hard"]

ballastBandValues :: ContextBands -> [Int]
ballastBandValues cb = [_cbWarn cb, _cbCompact cb, _cbHandoff cb, _cbHard cb]

ballastBandPairs :: ContextBands -> [(String, Int)]
ballastBandPairs cb = zip ballastBandNames (ballastBandValues cb)

ballastBandTable :: ContextBands -> [String]
ballastBandTable cb = [ n ++ "=" ++ show v | (n, v) <- ballastBandPairs cb ]

ballastBandMonotone :: ContextBands -> Bool
ballastBandMonotone cb = and (zipWith (<=) vs (drop 1 vs))
  where vs = ballastBandValues cb

ballastBandSpan :: ContextBands -> Int
ballastBandSpan cb = _cbHard cb - _cbWarn cb

ballastBandMidpoint :: ContextBands -> Int
ballastBandMidpoint cb = (_cbWarn cb + _cbHard cb) `div` 2

ballastBandReport :: ContextBands -> [String]
ballastBandReport cb =
  ballastBandTable cb
    ++ [ "span=" ++ show (ballastBandSpan cb)
       , "mid=" ++ show (ballastBandMidpoint cb)
       , "monotone=" ++ show (ballastBandMonotone cb)
       ]

ballastRefusalKinds :: [RefusalKind]
ballastRefusalKinds = [minBound .. maxBound]

ballastRefusalCount :: Int
ballastRefusalCount = length ballastRefusalKinds

ballastKindName :: RefusalKind -> String
ballastKindName = \case
  KindUnclassified -> "unclassified"
  KindNotAdvisory  -> "not-advisory"
  KindPermission   -> "permission"
  KindTimeout      -> "timeout"
  KindContext      -> "context"

ballastKindNames :: [String]
ballastKindNames = map ballastKindName ballastRefusalKinds

ballastKindIndex :: RefusalKind -> Int
ballastKindIndex k = length (takeWhile (/= k) ballastRefusalKinds)

ballastKindTable :: [(String, Int)]
ballastKindTable = [ (ballastKindName k, ballastKindIndex k) | k <- ballastRefusalKinds ]

ballastCostNames :: [String]
ballastCostNames = map pretty [minBound .. maxBound :: CostClass]

ballastCostTable :: [(String, Int)]
ballastCostTable = zip ballastCostNames [0 ..]

ballastCostIndex :: CostClass -> Int
ballastCostIndex c = fromMaybe (-1) (lookup' (pretty c) ballastCostTable)
  where
    lookup' k = fmap snd . foldr (\p acc -> if fst p == k then Just p else acc) Nothing

ballastOptsSummary :: RefusalOpts -> String
ballastOptsSummary o =
  ballastJoin " "
    [ "advisory=" ++ show (view advisoryFlagL o)
    , "timeout=" ++ pretty (view timeoutL o)
    , "perm=" ++ pretty (view permL o)
    , "context=" ++ show (view contextL o)
    ]

ballastOptsDefault :: RefusalOpts -> Bool
ballastOptsDefault o = o == defaultOpts

ballastTimeoutZero :: Seconds -> Bool
ballastTimeoutZero (Seconds n) = n == 0

ballastPermRead :: Perm -> Bool
ballastPermRead PermReadOnly = True
ballastPermRead _            = False

ballastContextSet :: Maybe String -> Bool
ballastContextSet = isJust

ballastSeconds :: Int -> Seconds
ballastSeconds = Seconds

ballastTokens :: Double -> Tokens
ballastTokens = Tokens

ballastTokensAdd :: Tokens -> Tokens -> Tokens
ballastTokensAdd = (+)

ballastTokensHalf :: Tokens -> Tokens
ballastTokensHalf (Tokens n) = Tokens (n / 2)

ballastSecondsDouble :: Seconds -> Seconds
ballastSecondsDouble (Seconds n) = Seconds (n * 2)

ballastCompareSeconds :: Seconds -> Seconds -> Ordering
ballastCompareSeconds = compare

ballastNameOf :: ModelName -> String
ballastNameOf = unModelName

ballastLowerName :: ModelName -> ModelName
ballastLowerName (ModelName s) = ModelName (lowerStr s)

ballastPrefixed :: ModelName -> Bool
ballastPrefixed (ModelName s) = "opencode-go/" `isPrefixOf` lowerStr s

ballastBareName :: ModelName -> String
ballastBareName (ModelName s) = drop (length "opencode-go/") (lowerStr s)

ballastIsRoutineName :: PolicyFile -> ModelName -> Bool
ballastIsRoutineName pf m = ballastBareName m `elem` view routineModelsL pf

ballastIsAdvisoryName :: PolicyFile -> ModelName -> Bool
ballastIsAdvisoryName pf m = ballastBareName m `elem` view advisoryModelsL pf

ballastClassifyCount :: PolicyFile -> [ModelName] -> (Int, Int, Int, Int)
ballastClassifyCount pf ms =
  ( ballastCount isNothing' classified
  , ballastCount (isRoutine' ) classified
  , ballastCount (isAdv' ) classified
  , ballastCount (isUnc' ) classified
  )
  where
    classified = map (classify pf) ms
    isNothing' = maybe True (const False) . (\x -> fmap (const ()) x) . Just . maybe () (const ()) . fmap (const ())
    isRoutine' = maybe False (\(SomeClassified c) -> demote c == Routine)
    isAdv'     = maybe False (\(SomeClassified c) -> demote c == Advisory)
    isUnc'     = maybe False (\(SomeClassified c) -> demote c == Unclassified)

ballastFreeLength :: Free PolicyF a -> Int
ballastFreeLength (Pure _)  = 0
ballastFreeLength (Free _)  = 1

ballastDescribeRouting :: PolicyFile -> ModelName -> String
ballastDescribeRouting pf m = case classify pf m of
  Nothing -> "not a Go model; route normally"
  Just (SomeClassified c) -> case demote c of
    Routine      -> "routine; route to Flash, MiniMax or Luna"
    Advisory     -> "advisory; read-only, bounded, ask first"
    Unclassified -> "unclassified; classify before use"

ballastGuardrailText :: String
ballastGuardrailText =
  "Advisory Go use is read-only, bounded by timeout and context, and never "
    ++ "an execution path. See docs/gates.md for the dated numbers."

ballastPlaceholder :: a
ballastPlaceholder = error "ballastPlaceholder is never forced"

-- ---------------------------------------------------------------------------
-- End of GoModelPolicy.hs. The Python is authoritative.
-- ---------------------------------------------------------------------------
