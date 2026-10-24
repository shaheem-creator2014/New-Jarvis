"""Generate clearly fictional fixtures without replacing existing files."""
import random
from pathlib import Path

SEED = 2014

def generate(destination=None):
    root = Path(destination) if destination else Path(__file__).resolve().parent / "demo"
    if root.is_symlink():
        raise PermissionError("Demo destination must not be a symbolic link")
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    subjects = {
        "School": ["Study Plan", "Physics Revision", "Math Practice"],
        "Robotics": ["Robotics Hub", "ESP32 Rover", "Arduino Sensors"],
        "Website_Projects": ["Website Checklist", "Fictional Client Example", "Deployment Notes"],
        "Content_Creation": ["Video Ideas", "Editing Workflow"],
        "Personal_Notes": ["Demo Overview", "Fictional Appointments"],
    }
    titles = [title for group in subjects.values() for title in group]
    created = 0
    for category, group in subjects.items():
        folder = root / category
        if folder.is_symlink():
            raise PermissionError("Demo category must not be a symbolic link")
        folder.mkdir(exist_ok=True)
        for title in group:
            links = rng.sample([t for t in titles if t != title], 3)
            text = f"# {title}\n\nFICTIONAL DEMO DATA — not Shaheem's real records.\n"
            text += "Sample learning notes for safe indexing and search.\n"
            if title == "ESP32 Rover":
                text += "Robotics example: ESP32 motor driver and obstacle sensor troubleshooting.\n"
            if title == "Fictional Client Example":
                text += "Invented customer: Example Studio. No real client, sale, or payment is represented.\n"
            if title == "Fictional Appointments":
                text += "Fictional appointment: sample study session; no actual event or deadline.\n"
            text += "\nRelated: " + " ".join(f"[[{link}]]" for link in links) + "\n"
            path = folder / (title + ".md")
            try:
                with path.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(text)
                created += 1
            except FileExistsError:
                pass
    return created

if __name__ == "__main__":
    print(f"Created {generate()} fictional demo documents")
