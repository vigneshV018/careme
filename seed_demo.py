"""
seed_demo.py - Manual Demo Circle Seeder for CareMe.
Run this script anytime to initialize or reset the demo circle with:
- Elder Lakshmi (PIN 1234, passcode 482915)
- Arun (Son), Priya (Daughter), Meena (Caregiver)
- 7-day adherence history and appointment with Dr. Ramesh
"""

import sys
from seed import seed

if __name__ == "__main__":
    print("CareMe: Seeding demo care circle...")
    seed()
    print("CareMe: Demo care circle seeded successfully!")

