import json
import sounddevice as sd
import vosk

MODEL_PATH = "models/vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
DEVICE = 2
BLOCK_SIZE = 4000

GRAMMAR = json.dumps([
    "volume up",
    "volume down",
    "mute",
    "turn sound on",
    "enable sound",
    "play",
    "pause",
    "next",
    "previous",
    "increase volume",
    "decrease volume",
    "turn it up",
    "turn it down",
    "silence",
    "sound on",
    "resume",
    "stop playback",
    "next track",
    "previous track",
    "[unk]"
])

print("Loading Vosk model...")
model = vosk.Model(MODEL_PATH)

recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE, GRAMMAR)
recognizer.SetMaxAlternatives(5)

print("\nGrammar-based VAMC recognition test")
print("Commands to test: sound on, turn sound on, enable sound, and pause")
print("Press Enter, speak one command, then wait.")
print("Press Ctrl+C to stop.\n")

try:
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        device=DEVICE,
        dtype="int16",
        channels=1,
    ) as stream:

        while True:
            input("Press Enter to record: ")
            recognizer.Reset()

            print("Speak now...")

            while True:
                audio, _ = stream.read(BLOCK_SIZE)

                if recognizer.AcceptWaveform(bytes(audio)):
                    result = json.loads(recognizer.Result())
                    print("\nRecognition result:")
                    print(json.dumps(result, indent=2))
                    break

except KeyboardInterrupt:
    print("\nTest stopped.")
