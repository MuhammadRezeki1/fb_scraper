# ============================================================
# SENTIMENT ANALYZER V2 - HYBRID + GEMINI
# IndoBERT + Kamus + Sarcasm Detection + Gemini 1.5 Pro
# ============================================================
# Strategi 4-layer:
#   1. RULE    : Hate keyword eksplisit + negation handling
#   2. SARCASM : Detect sarkasme indicator (regex pattern)
#   3. IndoBERT: ML model untuk yang ambigu
#   4. GEMINI  : Validator untuk komentar confidence rendah
#
# Mode:
#   - "hybrid"    -> kamus + IndoBERT + Gemini validator (RECOMMENDED)
#   - "ml_only"   -> IndoBERT + Gemini validator
#   - "rule_only" -> kamus saja, no download, instant
#
# Gemini aktif kalau GEMINI_ENABLED=True di .env
# Gemini dipanggil hanya kalau IndoBERT confidence < GEMINI_CONFIDENCE_THRESHOLD
# ============================================================

import re
import os
import json
import time
import warnings
from typing import Any, Callable, Dict, List, Optional, cast
import emoji

# ── LOAD .env PALING AWAL ────────────────────────────────────
# Harus sebelum apapun yang pakai os.getenv()
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # kalau dotenv belum install, pakai env system

warnings.filterwarnings("ignore")

langdetect_detect: Optional[Callable[[str], str]] = None
try:
    from langdetect import detect as langdetect_detect
    LANGDETECT_OK = True
except Exception:
    LANGDETECT_OK = False


# ============================================================
# KAMUS
# ============================================================

POSITIVE_ID = {
    "bagus", "baik", "keren", "mantap", "mantul", "hebat", "luar biasa",
    "sempurna", "indah", "cantik", "ganteng", "suka", "cinta", "sayang",
    "senang", "bahagia", "bangga", "sukses", "berhasil", "pintar", "rajin",
    "bersyukur", "terima kasih", "makasih", "masyaallah", "subhanallah",
    "alhamdulillah", "barakallah", "amin", "aamiin",
    "kece", "top", "jos", "uwu", "gemes", "gemoy", "lucu", "imut",
    "sultan", "legend", "epic", "auto", "gokil abis", "mantap jiwa",
    "lanjutkan", "semangat", "inspiratif", "bijak", "kreatif", "inovatif",
    "setuju", "benar", "tepat", "mendukung", "support", "dukung",
    "peduli", "perhatian", "bermanfaat", "berguna", "bermutu",
    "sehat selalu", "panjang umur", "berkah", "barokah", "rahmat",
    "lindungi", "lindungilah", "berkati",
    "good", "great", "nice", "wow", "amazing", "perfect", "love", "best",
}

NEGATIVE_ID = {
    "jelek", "buruk", "payah", "gagal", "salah", "bohong", "dusta",
    "tipu", "menipu", "penipu", "curang", "tidak suka", "benci",
    "muak", "jijik", "kecewa", "sedih", "susah", "sulit", "menderita",
    "sakit", "lelah", "capek", "malu", "takut", "cemas", "khawatir",
    "marah", "kesal", "sebal", "bosan", "jengkel", "frustrasi",
    "rugi", "hancur", "rusak", "parah", "gawat", "sial", "apes",
    "nyesel", "nyesal", "salah pilih", "mundur", "dilengserkan",
    "anjlok", "merosot", "menurun", "ambruk", "ambyar", "gagal total",
    "menderita", "sengsara", "miskin", "melarat", "kelaparan",
    "korup", "korupsi", "koruptor", "pengkhianat", "khianat",
    "menipu rakyat", "bohongi", "ingkar janji", "janji palsu",
    "lebay", "alay", "norak", "garing", "receh banget",
    "drama", "drama queen", "halu", "delulu", "toxic",
    "lebih baik", "harusnya", "seharusnya", "kalau saja",
    "minta maaf", "tolong mundur", "udah cukup",
    "bad", "worst", "terrible", "awful", "horrible", "trash",
}

HATE_WORDS_ID = {
    "anjing", "anjir", "anjg", "babi", "bangsat", "bajingan",
    "kampret", "keparat", "berengsek", "brengsek", "sialan",
    "goblok", "gblk", "tolol", "idiot", "bodoh banget", "dungu",
    "setan", "iblis", "laknat", "terkutuk",
    "anjay", "anying", "anjink",
    "bgst", "bngst", "bjgn", "bjg",
    "gblg", "gblok", "tll", "tlol",
    "jelek banget", "buluk", "kumel",
    "mati aja", "mati lu", "matilu", "matiin",
    "bunuh", "bunuh diri", "habisi",
    "kafir", "sesat", "penista", "penistaan",
    "kontol", "kntl", "kntol", "kontoi", "kntoi",
    "memek", "mmk", "ngentot", "ngntt",
    "asu", "dancok", "jancuk", "jancok",
}

TOXIC_WORDS_ID = {
    "sok", "sok pinter", "sok tau", "sok suci",
    "munafik", "hipokrit", "pencitraan", "drama",
    "egois", "serakah", "rakus", "tamak",
    "sombong", "arogan", "congkak", "tinggi hati",
    "pengecut", "penakut", "cemen",
    "tukang bohong", "pembohong", "pendusta",
    "hina dina", "rendahan", "kacangan",
    "halu", "delulu", "ngigau", "ngelantur",
    "bucin", "fanatik buta", "fanboy", "fangirl buta",
}

HUMOR_WORDS_ID = {
    "wkwk", "wkwkwk", "wkwkwkwk", "haha", "hahaha", "hehe", "hihi",
    "xixi", "kwkw", "lol", "lmao", "rofl", "ngakak", "ngek", "kocak",
    "lucu banget", "gila sih", "anjir lucu", "gokil",
    "auto", "epic", "legend", "sultan mode",
    "mager", "gabut", "rebahan",
}

SARCASM_PATTERNS = [
    re.compile(r'\b(wow|wah|hebat|mantap|bagus)\s+(banget|sekali|amat|nih|ya|deh)?\s*[😂🤣😅🙃]', re.I),
    re.compile(r'\bkualitas\s+(presiden|pejabat|menteri|pemimpin)', re.I),
    re.compile(r'\bbgini\s+(kualitas|hasil|kerjaannya)', re.I),
    re.compile(r'^(sehat|panjang umur|sukses)\s+selalu\b.*\?', re.I),
    re.compile(r'\b(makan|ajak makan)\s+(noh|tuh|aja)\b', re.I),
    re.compile(r'\banek\s*(noh|tuh)\b', re.I),
    re.compile(r'\bgemoy\s*[😂🤣]', re.I),
    re.compile(r'\bantek\s+antek\b', re.I),
    re.compile(r'\b(kapan|nunggu)\s+(mundur|maaf|lengser)', re.I),
    re.compile(r'\bbjir\b|\banjir\s+(parah|sih|banget)', re.I),
    re.compile(r'😂\s*\?$|🤣\s*\?$'),
    re.compile(r'\b(ternyata|kayanya|kelihatannya)\s+\w+.{0,30}\s+(lebih|jauh lebih)\s+(tajam|hebat|baik|pintar|kuat)', re.I),
    re.compile(r'\b(rakyat|warga)\s+(happy|senang|sejahtera)\s*\?', re.I),
    re.compile(r'\bmikir\s+(pak|bu|woi|wo)\b', re.I),
    re.compile(r'\b(diobok|diobok-obok|diobok obok)\b', re.I),
    re.compile(r'\b(kapak|senapan|jenderal)\b.{0,40}\b(tukang|rakyat)\b', re.I),
    re.compile(r'👏\s*👏', re.I),
    re.compile(r'\b(ga|gak|tidak|tak|kaga)\s+berani\b.*\?', re.I),
    re.compile(r'\b(pilih|tinggal)\s+(mundur|dilengserkan|turun)', re.I),
    re.compile(r'\bternyata\s+.{0,30}\s+begini\b', re.I),
    re.compile(r'\bpantesan\b', re.I),
    re.compile(r'\bsekalinya\s+jadi\b', re.I),
]

WELLWISH_PATTERNS = [
    re.compile(r'\bsehat\s+selalu\b', re.I),
    re.compile(r'\bpanjang\s+umur\b', re.I),
    re.compile(r'\bsemoga\s+(sukses|sehat|berkah|lancar|diberkahi)', re.I),
    re.compile(r'\bbarakallah\b|\bbarokallah\b', re.I),
    re.compile(r'\bmasyaallah\b|\bsubhanallah\b|\balhamdulillah\b', re.I),
    re.compile(r'\bsemoga\s+\w+', re.I),
]

NEGATIONS = {"tidak", "ga", "gak", "ngga", "engga", "enggak", "nggak",
             "bukan", "tak", "blm", "belum", "kagak", "kaga", "ndak",
             "nope", "no", "never"}


# ============================================================
# MAIN ANALYZER
# ============================================================

class SentimentAnalyzerV2:

    def __init__(self, mode: str = "hybrid", verbose: bool = True):
        self.mode    = mode
        self.verbose = verbose

        self.ml_model    = None
        self.ml_pipeline = None
        self.tokenizer   = None
        self.device      = "cpu"
        self.gemini_model = None

        # Baca config SETELAH load_dotenv() sudah dipanggil di atas
        self.gemini_enabled   = os.getenv("GEMINI_ENABLED", "False").strip().lower() == "true"
        self.gemini_threshold = float(os.getenv("GEMINI_CONFIDENCE_THRESHOLD", "0.70").strip())
        self._gemini_call_times: List[float] = []

        if self.verbose:
            print(f"   [DEBUG] GEMINI_ENABLED env = {repr(os.getenv('GEMINI_ENABLED'))}")
            print(f"   [DEBUG] gemini_enabled parsed = {self.gemini_enabled}")

        if mode in ("hybrid", "ml_only"):
            self._load_indobert()

        if self.gemini_enabled:
            self._load_gemini()
        else:
            print("ℹ️  Gemini tidak aktif (GEMINI_ENABLED bukan True di .env)")

    # ── INDOBERT LOADER ────────────────────────────────────────

    def _load_indobert(self):
        try:
            if self.verbose:
                print("🤖 Loading IndoBERT sentiment model...")
                print("   (first time: download ~440MB, after: instant load)")

            os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
            os.environ['TRANSFORMERS_NO_ADVISORY_WARNINGS'] = '1'

            from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
            import torch

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            device_id = 0 if self.device == "cuda" else -1

            model_name = "w11wo/indonesian-roberta-base-sentiment-classifier"
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.ml_model  = AutoModelForSequenceClassification.from_pretrained(model_name)

            if self.device == "cuda":
                self.ml_model = self.ml_model.to("cuda")

            self.ml_model.eval()

            self.ml_pipeline = pipeline(  # type: ignore
                task="sentiment-analysis",
                model=self.ml_model,
                tokenizer=self.tokenizer,
                device=device_id,
                truncation=True,
                max_length=512,
            )

            if self.verbose:
                print(f"✅ IndoBERT loaded on {self.device.upper()}")

        except ImportError:
            print("⚠️  Module 'transformers' atau 'torch' belum ter-install.")
            print("   Install: pip install transformers torch")
            print("   Fallback ke mode rule_only")
            self.mode = "rule_only"
            self.ml_model = None
        except Exception as e:
            print(f"⚠️  Gagal load IndoBERT: {e}")
            print("   Fallback ke mode rule_only")
            self.mode = "rule_only"
            self.ml_model = None

    # ── GEMINI LOADER ──────────────────────────────────────────

    def _load_gemini(self):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            print("⚠️  GEMINI_API_KEY tidak ditemukan di .env")
            self.gemini_model = None
            return

        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)

            self.gemini_model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                generation_config=genai.types.GenerationConfig(  # type: ignore[call-arg]
                    temperature=0.1,
                    max_output_tokens=120,
                    top_p=0.8,
                ),  # type: ignore[assignment]
            )

            # Ping test validasi key
            test = self.gemini_model.generate_content('Reply with: {"ok": true}')
            _ = test.text

            if self.verbose:
                print(f"✅ Gemini 1.5 Pro loaded (threshold: confidence < {self.gemini_threshold})")

        except ImportError:
            print("⚠️  Module 'google-generativeai' belum ter-install.")
            print("   Install: pip install google-generativeai")
            self.gemini_model = None
        except Exception as e:
            print(f"⚠️  Gagal load Gemini: {e}")
            self.gemini_model = None

    # ── UTILITIES ──────────────────────────────────────────────

    def _detect_language(self, text: str) -> str:
        if not LANGDETECT_OK or langdetect_detect is None:
            return "id"
        try:
            lang = langdetect_detect(text)
            return lang if lang in ("id", "en") else "id"
        except Exception:
            return "id"

    def _extract_emojis(self, text: str) -> List[str]:
        return [ch for ch in text if ch in emoji.EMOJI_DATA]

    def _normalize_text(self, text: str) -> str:
        t = text.lower().strip()
        t = re.sub(r'\s+', ' ', t)
        t = re.sub(r'(.)\1{2,}', r'\1\1', t)
        return t

    def _find_words_with_context(self, text: str, word_set: set) -> List[Dict]:
        text_norm = self._normalize_text(text)
        tokens = re.findall(r'\b[\w]+\b', text_norm)
        found = []

        for i, tok in enumerate(tokens):
            if tok in word_set:
                negated = False
                start = max(0, i - 2)
                for j in range(start, i):
                    if tokens[j] in NEGATIONS:
                        negated = True
                        break

                ctx_start = max(0, i - 1)
                ctx_end   = min(len(tokens), i + 2)
                phrase    = " ".join(tokens[ctx_start:ctx_end])

                found.append({
                    "word": tok,
                    "negated": negated,
                    "phrase_context": phrase,
                })
        return found

    def _has_sarcasm_indicator(self, text: str) -> bool:
        for pattern in SARCASM_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _has_wellwish_indicator(self, text: str) -> bool:
        if "?" in text:
            return False
        for pattern in WELLWISH_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _check_hate_context(self, hate_findings: List[Dict], full_text: str) -> List[str]:
        legitimate = []
        text_lower = full_text.lower()

        SAFE_PHRASES = {
            "mati": ["mati lampu", "mati listrik", "mati gaya", "mati rasa",
                     "garis mati", "kunci mati", "kata mati", "harga mati"],
            "bunuh": ["bunuh waktu", "membunuh waktu", "bunuh nyamuk"],
            "anjir": [],
            "setan": ["setan merah", "kupu setan"],
        }

        for h in hate_findings:
            w = h["word"]
            safe_list = SAFE_PHRASES.get(w, [])
            is_safe = any(safe in text_lower for safe in safe_list)
            if not is_safe and not h["negated"]:
                legitimate.append(w)
        return legitimate

    # ── GEMINI RATE LIMITER ────────────────────────────────────

    def _gemini_rate_limit_ok(self) -> bool:
        now = time.time()
        self._gemini_call_times = [t for t in self._gemini_call_times if now - t < 60]
        if len(self._gemini_call_times) >= 12:
            return False
        self._gemini_call_times.append(now)
        return True

    # ── ML INFERENCE ───────────────────────────────────────────

    def _ml_predict(self, text: str) -> Optional[Dict]:
        if not self.ml_pipeline:
            return None
        try:
            result = self.ml_pipeline(text[:1500])[0]
            label  = result["label"].lower()
            score  = float(result["score"])

            sentiment_map = {
                "positive": "POSITIVE",
                "negative": "NEGATIVE",
                "neutral":  "NEUTRAL",
            }
            return {
                "sentiment":  sentiment_map.get(label, "NEUTRAL"),
                "confidence": score,
            }
        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  ML predict error: {e}")
            return None

    # ── GEMINI INFERENCE ───────────────────────────────────────

    def _gemini_predict(self, text: str) -> Optional[Dict]:
        if not self.gemini_model:
            return None

        if not self._gemini_rate_limit_ok():
            if self.verbose:
                print("   ⏳ Gemini rate limit (12/mnt), skip")
            return None

        prompt = f"""Kamu adalah sistem analisis sentimen komentar media sosial Indonesia.

Analisis sentimen komentar berikut. Perhatikan sarkasme, bahasa gaul, dan konteks budaya Indonesia.

Aturan:
- Sindiran/ironi meski pakai kata positif = NEGATIVE + is_sarcasm: true
- "Pantesan dulu kalah terus, begini kualitasnya" = NEGATIVE
- "syarat pemimpin: jujur... bapak ga punya semua itu" = NEGATIVE
- Kritik sopan formal = NEGATIVE
- Minta mundur/lengser/ganti = NEGATIVE
- "zaman X lebih baik dari bapak" = NEGATIVE
- Doa tulus tanpa tanda tanya = POSITIVE
- Emoji 🙏 lihat konteks — bisa positif atau sarkasme
- Emoji 💀😂 di konteks kritik = sarkasme NEGATIVE
- is_hate_speech: true hanya kalau ada umpatan kasar (anjing, bangsat, dll)
- is_toxic: true kalau condescending (sok pintar, pencitraan, dll)

Jawab HANYA JSON satu baris tanpa markdown:
{{"sentiment":"POSITIVE","is_sarcasm":false,"is_hate_speech":false,"is_toxic":false,"confidence":0.85}}

Komentar: "{text[:800]}"
"""

        raw = ""
        try:
            response = self.gemini_model.generate_content(prompt)
            raw = response.text.strip()
            raw = re.sub(r'```json\s*|```\s*', '', raw).strip()

            json_match = re.search(r'\{[^}]+\}', raw)
            if not json_match:
                return None

            result = json.loads(json_match.group())

            sentiment = str(result.get("sentiment", "NEUTRAL")).upper()
            if sentiment not in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
                sentiment = "NEUTRAL"

            return {
                "sentiment":      sentiment,
                "confidence":     float(result.get("confidence", 0.75)),
                "is_sarcasm":     bool(result.get("is_sarcasm", False)),
                "is_hate_speech": bool(result.get("is_hate_speech", False)),
                "is_toxic":       bool(result.get("is_toxic", False)),
            }

        except json.JSONDecodeError as e:
            if self.verbose:
                print(f"   ⚠️  Gemini JSON error: {e} | raw: {(raw or '')[:80]}")
            return None
        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  Gemini error: {e}")
            return None

    # ── MAIN ANALYZE ───────────────────────────────────────────

    def analyze_sentiment(self, text: str) -> Dict:
        if not text or not text.strip():
            return self._empty_result()

        language    = self._detect_language(text)
        emojis_list = self._extract_emojis(text)

        # LAYER 1: Hate
        hate_findings    = self._find_words_with_context(text, HATE_WORDS_ID)
        legitimate_hate  = self._check_hate_context(hate_findings, text)
        is_hate_speech   = len(legitimate_hate) > 0

        # LAYER 2: Toxic
        toxic_findings   = self._find_words_with_context(text, TOXIC_WORDS_ID)
        legitimate_toxic = [t["word"] for t in toxic_findings if not t["negated"]]
        is_toxic         = (not is_hate_speech) and len(legitimate_toxic) > 0

        # Word findings
        pos_findings   = self._find_words_with_context(text, POSITIVE_ID)
        neg_findings   = self._find_words_with_context(text, NEGATIVE_ID)
        humor_words    = [w for w in HUMOR_WORDS_ID
                          if re.search(r'\b' + re.escape(w) + r'\b', text.lower())]

        positive_words = [p["word"] for p in pos_findings if not p["negated"]]
        negative_words = [n["word"] for n in neg_findings if not n["negated"]]
        negative_words.extend([p["word"] for p in pos_findings if p["negated"]])

        # LAYER 3: Sarcasm & Wellwish
        has_sarcasm  = self._has_sarcasm_indicator(text)
        has_wellwish = self._has_wellwish_indicator(text)

        # LAYER 4: ML / Rule
        sentiment       = "NEUTRAL"
        ml_confidence   = 0.0
        decision_source = "rule"

        if is_hate_speech:
            sentiment       = "HATE"
            decision_source = "rule_hate"

        elif self.mode in ("hybrid", "ml_only") and self.ml_pipeline:
            ml_result = self._ml_predict(text)
            if ml_result:
                sentiment       = ml_result["sentiment"]
                ml_confidence   = ml_result["confidence"]
                decision_source = "ml"

                if has_sarcasm and sentiment == "POSITIVE":
                    sentiment       = "NEGATIVE"
                    decision_source = "ml+sarcasm_flip"

                elif (has_wellwish and not has_sarcasm
                      and sentiment == "NEUTRAL"
                      and ml_confidence < 0.75
                      and len(negative_words) == 0):
                    sentiment       = "POSITIVE"
                    decision_source = "ml+wellwish_boost"

                elif ml_confidence < 0.6:
                    if len(negative_words) >= 2 and len(positive_words) == 0:
                        sentiment       = "NEGATIVE"
                        decision_source = "ml_lowconf+rule_neg"
                    elif len(positive_words) >= 2 and len(negative_words) == 0:
                        sentiment       = "POSITIVE"
                        decision_source = "ml_lowconf+rule_pos"

                # LAYER 5: GEMINI VALIDATOR
                if (self.gemini_enabled
                        and self.gemini_model
                        and ml_confidence < self.gemini_threshold
                        and decision_source == "ml"):

                    gemini_result = self._gemini_predict(text)
                    if gemini_result:
                        old = sentiment
                        sentiment       = gemini_result["sentiment"]
                        ml_confidence   = gemini_result["confidence"]
                        decision_source = "gemini"

                        if gemini_result["is_sarcasm"]:
                            has_sarcasm = True
                        if gemini_result["is_hate_speech"] and not is_hate_speech:
                            is_hate_speech  = True
                            sentiment       = "HATE"
                            decision_source = "gemini_hate"
                        if gemini_result["is_toxic"] and not is_toxic:
                            is_toxic = True

                        if self.verbose and old != sentiment:
                            print(f"   🔄 Gemini override: {old} -> {sentiment} "
                                  f"(conf: {ml_confidence:.2f})")

            else:
                sentiment       = self._rule_based_sentiment(positive_words, negative_words,
                                                             has_sarcasm, has_wellwish)
                decision_source = "rule_fallback"
        else:
            sentiment = self._rule_based_sentiment(positive_words, negative_words,
                                                   has_sarcasm, has_wellwish)

        if decision_source == "rule" and has_sarcasm and sentiment == "POSITIVE":
            sentiment       = "NEGATIVE"
            decision_source = "rule+sarcasm_flip"

        if (decision_source == "rule" and has_wellwish and not has_sarcasm
                and sentiment == "NEUTRAL" and len(negative_words) == 0):
            sentiment       = "POSITIVE"
            decision_source = "rule+wellwish_boost"

        hate_score = min(len(legitimate_hate) * 0.3, 1.0)
        if is_toxic:
            hate_score = max(hate_score, len(legitimate_toxic) * 0.1)

        return {
            "sentiment":       sentiment,
            "language":        language,
            "is_hate_speech":  is_hate_speech,
            "is_toxic":        is_toxic,
            "is_sarcasm":      has_sarcasm,
            "is_wellwish":     has_wellwish,
            "hate_score":      round(hate_score, 2),
            "hate_words":      legitimate_hate,
            "toxic_words":     legitimate_toxic,
            "positive_words":  positive_words,
            "negative_words":  negative_words,
            "humor_words":     humor_words,
            "emojis":          emojis_list,
            "ml_confidence":   round(ml_confidence, 3),
            "decision_source": decision_source,
            "vader_compound":  0.0,
        }

    def _rule_based_sentiment(self, pos_words: List[str], neg_words: List[str],
                              has_sarcasm: bool, has_wellwish: bool = False) -> str:
        if has_sarcasm:
            return "NEGATIVE"
        if has_wellwish and len(neg_words) == 0:
            return "POSITIVE"
        if len(pos_words) > len(neg_words):
            return "POSITIVE"
        if len(neg_words) > len(pos_words):
            return "NEGATIVE"
        return "NEUTRAL"

    def categorize_comment(self, text: str) -> str:
        analysis = self.analyze_sentiment(text)

        if analysis["is_hate_speech"]:
            return "HATE_SPEECH"
        if analysis["is_toxic"]:
            return "TOXIC"

        sentiment = analysis["sentiment"]
        if sentiment == "POSITIVE":
            return "POSITIVE"
        if sentiment == "NEGATIVE":
            return "NEGATIVE"
        if analysis["humor_words"]:
            return "HUMOR"
        return "NEUTRAL"

    def _empty_result(self) -> Dict:
        return {
            "sentiment": "NEUTRAL", "language": "id",
            "is_hate_speech": False, "is_toxic": False,
            "is_sarcasm": False, "is_wellwish": False,
            "hate_score": 0.0, "hate_words": [], "toxic_words": [],
            "positive_words": [], "negative_words": [], "humor_words": [],
            "emojis": [], "ml_confidence": 0.0,
            "decision_source": "empty", "vader_compound": 0.0,
        }


# Backward compat alias
SentimentAnalyzer = SentimentAnalyzerV2