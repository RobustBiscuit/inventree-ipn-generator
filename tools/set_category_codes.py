"""
One-time helper to populate the `sku_code` metadata field on InvenTree
PartCategories, so the IPN Generator plugin (category-aware mode) can build
SKUs from the category hierarchy.

Each category gets a short code stored in its metadata, e.g.:
    Resistors            -> {"sku_code": "RES"}
    0402                 -> {"sku_code": "0402"}
A part placed in Resistors/0402 then receives an IPN like "RES-0402-0001".

The CATEGORY_CODES mapping below is keyed by category NAME. Edit it to match
your own taxonomy. Names not present in your InvenTree are simply skipped.

Usage:
    python set_category_codes.py \
        --url https://your-inventree-url \
        --token YOUR_API_TOKEN \
        [--key sku_code] \
        [--dry-run]

Get your API token from InvenTree: Settings -> Account -> API Tokens
"""

import argparse
import requests

# Category name -> SKU code. Both top-level (primary) and sub-category
# (secondary) names live in one flat dict; each category stores only its own
# code. Edit freely to match your categories.
CATEGORY_CODES = {
    # --- Primary (top-level) categories ---
    "Antennas": "ANT",
    "Batteries": "BAT",
    "Capacitors": "CAP",
    "Connectors": "CON",
    "Diodes": "DIO",
    "Displays": "DIS",
    "Electromechanical": "ELM",
    "Fuses & Protection": "FUS",
    "Integrated Circuits": "IC",
    "Inductors": "IND",
    "Optoelectronics": "LED",
    "Mechanical & Hardware": "MEC",
    "Modules": "MOD",
    "Oscillators": "OSC",
    "PCBs & Pins": "PCB",
    "Power Supply": "PWR",
    "Resistors": "RES",
    "RF & Wireless": "RF",
    "Sensors": "SEN",
    "Transistors": "TRA",
    "Wires & Cables": "WRE",
    # --- Secondary (sub) categories ---
    "Through Hole": "THL",
    "Wire & Cable": "WRE",
    "Surface Mount": "SMD",
    "Lithium-Ion": "LIIO",
    "Lithium-Polymer": "LIPO",
    "Sealed Lead Acid": "SLA",
    "Kits": "KIT",
    "Polarized": "POL",
    "Safety Film": "SFT",
    "Tantalum": "TAN",
    "Battery": "BAT",
    "Panel Mount": "PNL",
    "Flow Switches": "FLW",
    "Navigation Switches": "NAV",
    "Pushbuttons": "PBT",
    "Potentiometers": "POT",
    "Rotary Switches": "RSW",
    "Slide Switches": "SLD",
    "Valves": "VAL",
    "Analog-to-Digital": "ADC",
    "Amplifiers": "AMP",
    "Battery Chargers": "CHG",
    "Communications": "COM",
    "Current Regulators": "CRR",
    "Digital-to-Analog": "DAC",
    "Drivers": "DRV",
    "EEPROM": "EEP",
    "I/O Expanders": "EXP",
    "Flash Memory": "FSH",
    "Inertial Measurement Units": "IMU",
    "Inverters & Logic": "INV",
    "Isolators": "ISO",
    "Magnetic & Hall Effect": "MAG",
    "Microcontrollers": "MPU",
    "Multiplexers": "MUX",
    "NOR Flash": "NOR",
    "Optocouplers": "OPT",
    "SRAM": "RAM",
    "Voltage References": "REF",
    "SIM Controllers": "SIM",
    "Switching Controllers": "SWC",
    "Timers": "TMR",
    "USB Controllers": "USC",
    "Enclosures": "BOX",
    "Electrical Fittings": "ELC",
    "Fasteners": "FST",
    "Heatsinks": "HSK",
    "Waterproofing": "WTP",
    "Compute Modules": "CMP",
    "Measurement Modules": "MES",
    "Solid State Drives": "SSD",
    "Breakout Boards": "BRKO",
    "Control Boards": "CTL",
    "Guide Pins": "GID",
    "Test Points": "TST",
    "AC-DC Supplies": "ACD",
    "DC-DC Converters": "DCD",
    "Power Relays": "REL",
    "Transformers": "TRA",
    "Linear Regulators": "LIN",
    "Shunt Regulators": "SHU",
    "Switching Regulators": "SWI",
    "433MHz": "433",
    "802.11 & 802.15.4": "802",
    "Attenuators": "ATN",
    "Cellular": "GSM",
    "Mesh Networks": "MSH",
    "Receivers": "RX",
    "Transmitters": "TX",
    "WiFi Modules": "WFI",
    "Absolute Pressure": "APS",
    "Environmental": "ENV",
    "Proximity": "PRX",
    "Ribbon Cables": "RBN",
    "Shielded Cables": "SHL",
    "Heat Shrink": "SHR",
    "Twisted Pair": "TWS",
    "Thermistors": "NTC",
    "0201": "0201",
    "0402": "0402",
    "0603": "0603",
    "0805": "0805",
    "1008": "1008",
    "1206": "1206",
    "1210": "1210",
    "1812": "1812",
    "2010": "2010",
    "2220": "2220",
    "2512": "2512",
    "4122": "4122",
    # Sub-categories whose name is already the SKU code
    "LED": "LED",
    "MIC": "MIC",
    "PWR": "PWR",
    "PCB": "PCB",
    "LPH": "LPH",
    "LPS": "LPS",
}


def get_all_categories(base_url, headers):
    categories = []
    url = f"{base_url}/api/part/category/?limit=100&offset=0"
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        categories.extend(data["results"])
        url = data.get("next")
    return categories


def get_metadata(base_url, headers, category_id):
    url = f"{base_url}/api/metadata/partcategory/pk/{category_id}/"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json().get("metadata") or {}


def set_metadata(base_url, headers, category_id, metadata, dry_run):
    url = f"{base_url}/api/metadata/partcategory/pk/{category_id}/"
    if dry_run:
        print(f"  [DRY RUN] PATCH {url}  metadata={metadata}")
        return
    resp = requests.patch(url, json={"metadata": metadata}, headers=headers)
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="InvenTree base URL (no trailing slash)")
    parser.add_argument("--token", required=True, help="InvenTree API token")
    parser.add_argument("--key", default="sku_code", help="Metadata key to write (default: sku_code)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without applying them")
    args = parser.parse_args()

    headers = {"Authorization": f"Token {args.token}"}

    print("Fetching categories...")
    categories = get_all_categories(args.url, headers)

    updated = []
    skipped = []

    for cat in categories:
        name = cat["name"]
        code = CATEGORY_CODES.get(name)
        if not code:
            skipped.append(f"  {cat['pathstring']}")
            continue

        # Merge into existing metadata so we don't clobber other keys.
        existing = {} if args.dry_run else get_metadata(args.url, headers, cat["pk"])
        existing[args.key] = code

        print(f"Setting {cat['pathstring']} -> {args.key}={code}")
        set_metadata(args.url, headers, cat["pk"], existing, args.dry_run)
        updated.append(f"  {cat['pathstring']} -> {code}")

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Updated {len(updated)} categories.")

    if skipped:
        print(f"\nSkipped {len(skipped)} categories with no code in CATEGORY_CODES:")
        print("\n".join(skipped))


if __name__ == "__main__":
    main()
