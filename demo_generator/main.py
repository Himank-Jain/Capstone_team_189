"""Print the synthetic scenario library without generating demo incidents."""

from .generator import DemoGenerator


def main() -> None:
    generator = DemoGenerator()
    print("Loaded demo generator with scenarios:")
    for scenario in generator.list_scenarios():
        print(f"- {scenario['value']}: {scenario['description']}")


if __name__ == "__main__":
    main()
