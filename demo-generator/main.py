from generator import DemoGenerator


def main() -> None:
    generator = DemoGenerator()
    print("Loaded demo generator with scenarios:")
    for scenario in generator.list_scenarios():
        print(f"- {scenario['name']}: {scenario['description']}")


if __name__ == "__main__":
    main()
