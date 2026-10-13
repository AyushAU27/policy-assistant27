"""Command line:  python -m policy_assistant "your question" --date 2026-08-20
No question given -> a small interactive prompt (remembers the merchant size between questions)."""
import argparse

from . import Conversation, verify


def main() -> None:
    p = argparse.ArgumentParser(prog="policy_assistant")
    p.add_argument("question", nargs="?")
    p.add_argument("--date", help="as-of date, YYYY-MM-DD (default 2026-08-15)")
    args = p.parse_args()
    verify()                      # fail loudly if the rule table ever drifts from the documents
    chat = Conversation()
    if args.question:
        print(chat.ask(args.question, args.date))
        return
    print("Ask a policy question (empty line to quit). Prefix with a date like '2026-09-05| ' to change it.")
    while True:
        line = input("\n> ").strip()
        if not line:
            break
        date, _, rest = line.partition("|")
        print()
        print(chat.ask(rest.strip(), date.strip()) if rest and len(date) == 10 else chat.ask(line, args.date))


if __name__ == "__main__":
    main()
