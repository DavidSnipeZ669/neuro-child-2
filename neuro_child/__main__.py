from neuro_child.trainer import Trainer

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Neuro-child trainer")
    parser.add_argument("--name", default="child")
    parser.add_argument("--llm-endpoint", default=None)
    parser.add_argument("--llm-model", default="gpt-4o-mini")
    args = parser.parse_args()
    t = Trainer(name=args.name, llm_endpoint=args.llm_endpoint, llm_model=args.llm_model)
    t.run_repl()


if __name__ == "__main__":
    main()
