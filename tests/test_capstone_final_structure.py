from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_scaffold_directories_exist():
    required_dirs = [
        ROOT / "frontend" / "src" / "app" / "dashboard",
        ROOT / "frontend" / "src" / "components" / "widgets",
        ROOT / "phase3" / "api",
        ROOT / "demo_generator" / "scenarios",
        ROOT / "docs" / "guides",
    ]
    for path in required_dirs:
        assert path.exists(), f"Missing required directory: {path}"


def test_required_guidance_documents_exist():
    required_files = [
        ROOT / "README.md",
        ROOT / "docs" / "guides" / "CAPSTONE-189_IMPLEMENTATION_GUIDE.md",
        ROOT / "docs" / "guides" / "PROJECT_DIRECTORY_STRUCTURE_GUIDE.md",
        ROOT / "docs" / "guides" / "TESTING_AND_VERIFICATION_GUIDE.md",
        ROOT / "frontend" / "package.json",
        ROOT / "phase3" / "api" / "app.py",
        ROOT / "demo_generator" / "main.py",
        ROOT / "demo_generator" / "generator.py",
    ]
    for path in required_files:
        assert path.exists(), f"Missing required file: {path}"
