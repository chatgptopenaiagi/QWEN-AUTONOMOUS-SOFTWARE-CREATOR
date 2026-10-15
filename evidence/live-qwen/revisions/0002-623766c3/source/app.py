import argparse
from greeting import greet

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="The name to greet")
    parser.add_argument("--upper", action="store_true", help="Uppercase the greeting")
    args = parser.parse_args()
    print(greet(args.name, args.upper))

if __name__ == "__main__":
    main()