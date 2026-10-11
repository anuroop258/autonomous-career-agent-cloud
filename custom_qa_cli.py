import argparse
from custom_qa_store import save_custom_qa, list_custom_qa, delete_custom_qa, find_custom_answer


def main():
    parser = argparse.ArgumentParser(description="Persistent custom application Q&A")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--question", required=True)
    add.add_argument("--answer", required=True)
    sub.add_parser("list")
    test = sub.add_parser("test")
    test.add_argument("--question", required=True)
    test.add_argument("--options", default="")
    rem = sub.add_parser("remove")
    rem.add_argument("--question", required=True)
    args = parser.parse_args()
    if args.cmd == "add":
        save_custom_qa(args.question, args.answer)
        print("Saved custom Q&A.")
    elif args.cmd == "list":
        rows = list_custom_qa()
        if not rows:
            print("No custom Q&A entries.")
        for row in rows:
            print(f"[{row['id']}] Q: {row['question']}\n    A: {row['answer']}")
    elif args.cmd == "test":
        options = [x.strip() for x in args.options.split("|") if x.strip()]
        print(find_custom_answer(args.question, options))
    elif args.cmd == "remove":
        count = delete_custom_qa(args.question)
        print(f"Deleted {count} entr{'y' if count == 1 else 'ies'}.")


if __name__ == "__main__":
    main()
