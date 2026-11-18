"""Ask the agent a question from the terminal.

    python -m agent.cli "What was our CAC for paid media in Q3 2025?"
    python -m agent.cli --mode no_docs "How many conversions did we have in 2025?"
"""
import argparse

from .agent import MODES, Text2SQLAgent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--mode", choices=MODES, default="with_docs")
    args = parser.parse_args()

    agent = Text2SQLAgent(mode=args.mode)
    result = agent.ask(args.question, verbose=True)
    print("\n" + "=" * 70)
    print(result.answer or f"(no answer) {result.error}")
    print("=" * 70)
    print(f"steps={result.steps} tokens_in={result.input_tokens} "
          f"tokens_out={result.output_tokens} time={result.seconds}s")


if __name__ == "__main__":
    main()
