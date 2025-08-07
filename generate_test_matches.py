#!/usr/bin/env python3
"""
Generate test_matches.csv based on valid.csv with controlled similarity levels.
Creates data for testing vector cosine similarity matching in Snowflake.
"""

import csv
import random
import re
from typing import List, Dict, Tuple
import uuid

# Configuration
EXACT_MATCH_COUNT = 50      # 10%
VERY_CLOSE_COUNT = 100      # 20% 
SOMEWHAT_CLOSE_COUNT = 100  # 20%
NOT_CLOSE_COUNT = 250       # 50%
TOTAL_RECORDS = 500

# SOURCE_SYSTEM distribution
SOURCE_SYSTEMS = [
    'sap_hmh', 'sfdc_hmh', 'sfdc_nwea', '112',
    'sis_pearson', 'erp_oracle', 'crm_edtech'
]

class TestDataGenerator:
    def __init__(self):
        self.valid_data = []
        self.output_data = []
        
        # Variation mappings
        self.abbreviations = {
            'Street': ['St', 'ST'],
            'Road': ['Rd', 'RD'], 
            'Drive': ['Dr', 'DR'],
            'Avenue': ['Ave', 'AVE'],
            'Boulevard': ['Blvd', 'BLVD'],
            'North': ['N', 'NORTH'],
            'South': ['S', 'SOUTH'], 
            'East': ['E', 'EAST'],
            'West': ['W', 'WEST'],
            'Northeast': ['NE', 'NORTHEAST'],
            'Southeast': ['SE', 'SOUTHEAST'],
            'Northwest': ['NW', 'NORTHWEST'],
            'Southwest': ['SW', 'SOUTHWEST'],
            'Elementary School': ['Elem School', 'Elementary Sch', 'Elem Sch'],
            'High School': ['HS', 'High Sch', 'Secondary School'],
            'Learning Center': ['Learning Centre', 'Educational Center', 'Education Center'],
            'Community College': ['Comm College', 'CC', 'Community Coll'],
            'School District': ['School Dist', 'Sch Dist', 'SD']
        }
        
        self.common_typos = {
            'Academy': ['Acadamy', 'Acadmey'],
            'Elementary': ['Elementry', 'Elmentary'],
            'Secondary': ['Secondry', 'Secandary'], 
            'Community': ['Comunity', 'Commmunity'],
            'Christian': ['Cristian', 'Chirstian'],
            'Learning': ['Learing', 'Lerning'],
            'District': ['Distict', 'Distrct'],
            'College': ['Collge', 'Colegee']
        }

    def load_valid_data(self, filename: str):
        """Load data from valid.csv"""
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            self.valid_data = list(reader)
        print(f"Loaded {len(self.valid_data)} records from {filename}")

    def generate_source_pkey(self) -> str:
        """Generate a unique SOURCE_PKEY"""
        return f"TEST_{uuid.uuid4().hex[:12].upper()}"

    def apply_case_variations(self, text: str) -> str:
        """Apply random case variations"""
        variations = [
            text.lower(),
            text.upper(), 
            text.title(),
            text
        ]
        return random.choice(variations)

    def apply_abbreviations(self, text: str, aggressive: bool = False) -> str:
        """Apply abbreviation substitutions"""
        result = text
        items = list(self.abbreviations.items())
        if aggressive:
            # Use more abbreviations for lower similarity
            sample_size = min(len(items), random.randint(2, 4))
        else:
            # Use fewer abbreviations for higher similarity  
            sample_size = min(len(items), random.randint(1, 2))
            
        for original, alternatives in random.sample(items, sample_size):
            if original in result:
                result = result.replace(original, random.choice(alternatives))
        return result

    def apply_typos(self, text: str, num_typos: int = 1) -> str:
        """Apply common typos"""
        result = text
        available_typos = [(k, v) for k, v in self.common_typos.items() if k in result]
        
        if available_typos and num_typos > 0:
            typos_to_apply = min(num_typos, len(available_typos))
            for original, alternatives in random.sample(available_typos, typos_to_apply):
                result = result.replace(original, random.choice(alternatives))
        return result

    def vary_address_number(self, address: str) -> str:
        """Slightly modify street numbers"""
        # Find numbers at the start of the address
        match = re.match(r'^(\d+)(.*)$', address)
        if match:
            number = int(match.group(1))
            rest = match.group(2)
            # Change number by +/- 1-3
            new_number = number + random.choice([-3, -2, -1, 1, 2, 3])
            return f"{max(1, new_number)}{rest}"
        return address

    def vary_postal_code(self, postal_code: str) -> str:
        """Modify postal codes slightly"""
        if '-' in postal_code:
            # ZIP+4 format
            parts = postal_code.split('-')
            if len(parts[0]) == 5 and parts[0].isdigit():
                # Sometimes remove +4
                if random.random() < 0.3:
                    return parts[0]
                # Sometimes change last digit of +4
                if len(parts[1]) == 4 and parts[1].isdigit():
                    new_last = str(random.randint(0, 9))
                    return f"{parts[0]}-{parts[1][:-1]}{new_last}"
        elif len(postal_code) == 5 and postal_code.isdigit():
            # Change last 1-2 digits
            if random.random() < 0.5:
                # Change last digit
                new_last = str(random.randint(0, 9))
                return postal_code[:-1] + new_last
            else:
                # Change last 2 digits
                new_last_two = f"{random.randint(0, 9)}{random.randint(0, 9)}"
                return postal_code[:-2] + new_last_two
        return postal_code

    def create_exact_match(self, record: Dict) -> Dict:
        """Create exact match (only SOURCE_PKEY and SOURCE_SYSTEM change)"""
        return {
            'SOURCE_PKEY': self.generate_source_pkey(),
            'NAME': record['NAME'],
            'SOURCE_SYSTEM': random.choice(SOURCE_SYSTEMS),
            'ADDRESS_LINE_1': record['ADDRESS_LINE_1'],
            'ADDRESS_LINE_2': record['ADDRESS_LINE_2'],
            'CITY': record['CITY'],
            'STATE': record['STATE'],
            'POSTAL_CODE': record['POSTAL_CODE'],
            'COUNTRY': record['COUNTRY']
        }

    def create_very_close_match(self, record: Dict) -> Dict:
        """Create very close match (>0.98 similarity)"""
        name = record['NAME']
        address = record['ADDRESS_LINE_1']
        
        # Apply minor variations
        if random.random() < 0.7:
            name = self.apply_case_variations(name)
        if random.random() < 0.5:
            address = self.apply_abbreviations(address, aggressive=False)
        if random.random() < 0.3:
            name = name.replace("'", "")  # Remove apostrophes
            
        return {
            'SOURCE_PKEY': self.generate_source_pkey(),
            'NAME': name,
            'SOURCE_SYSTEM': random.choice(SOURCE_SYSTEMS),
            'ADDRESS_LINE_1': address,
            'ADDRESS_LINE_2': record['ADDRESS_LINE_2'],
            'CITY': record['CITY'],
            'STATE': record['STATE'],
            'POSTAL_CODE': record['POSTAL_CODE'],
            'COUNTRY': record['COUNTRY']
        }

    def create_somewhat_close_match(self, record: Dict) -> Dict:
        """Create somewhat close match (>0.93 similarity)"""
        name = self.apply_abbreviations(record['NAME'], aggressive=True)
        address = self.apply_abbreviations(record['ADDRESS_LINE_1'], aggressive=True)
        postal_code = record['POSTAL_CODE']
        
        # Apply moderate variations
        if random.random() < 0.4:
            name = self.apply_typos(name, 1)
        if random.random() < 0.3:
            address = self.vary_address_number(address)
        if random.random() < 0.3:
            postal_code = self.vary_postal_code(postal_code)
            
        return {
            'SOURCE_PKEY': self.generate_source_pkey(),
            'NAME': name,
            'SOURCE_SYSTEM': random.choice(SOURCE_SYSTEMS),
            'ADDRESS_LINE_1': address,
            'ADDRESS_LINE_2': record['ADDRESS_LINE_2'],
            'CITY': record['CITY'],
            'STATE': record['STATE'],
            'POSTAL_CODE': postal_code,
            'COUNTRY': record['COUNTRY']
        }

    def create_not_close_match(self, record: Dict) -> Dict:
        """Create not very close match (<0.93 similarity)"""
        name = self.apply_abbreviations(record['NAME'], aggressive=True)
        name = self.apply_typos(name, random.randint(1, 2))
        
        address = self.apply_abbreviations(record['ADDRESS_LINE_1'], aggressive=True)
        address = self.vary_address_number(address)
        
        postal_code = self.vary_postal_code(record['POSTAL_CODE'])
        
        # Additional aggressive changes
        if random.random() < 0.3:
            # Change street type completely
            street_types = ['St', 'Ave', 'Rd', 'Dr', 'Blvd', 'Ct', 'Ln', 'Way']
            for st_type in street_types:
                if st_type in address:
                    new_type = random.choice([t for t in street_types if t != st_type])
                    address = address.replace(st_type, new_type)
                    break
                    
        return {
            'SOURCE_PKEY': self.generate_source_pkey(),
            'NAME': name,
            'SOURCE_SYSTEM': random.choice(SOURCE_SYSTEMS),
            'ADDRESS_LINE_1': address,
            'ADDRESS_LINE_2': record['ADDRESS_LINE_2'],
            'CITY': record['CITY'],
            'STATE': record['STATE'],
            'POSTAL_CODE': postal_code,
            'COUNTRY': record['COUNTRY']
        }

    def generate_test_data(self):
        """Generate all test data according to distribution"""
        print("Generating test data...")
        
        # Shuffle source data for random sampling
        source_records = self.valid_data.copy()
        random.shuffle(source_records)
        
        record_index = 0
        
        # Generate exact matches
        print(f"Creating {EXACT_MATCH_COUNT} exact matches...")
        for i in range(EXACT_MATCH_COUNT):
            match = self.create_exact_match(source_records[record_index])
            self.output_data.append(match)
            record_index += 1
            
        # Generate very close matches
        print(f"Creating {VERY_CLOSE_COUNT} very close matches...")
        for i in range(VERY_CLOSE_COUNT):
            match = self.create_very_close_match(source_records[record_index])
            self.output_data.append(match)
            record_index += 1
            
        # Generate somewhat close matches
        print(f"Creating {SOMEWHAT_CLOSE_COUNT} somewhat close matches...")
        for i in range(SOMEWHAT_CLOSE_COUNT):
            match = self.create_somewhat_close_match(source_records[record_index])
            self.output_data.append(match)
            record_index += 1
            
        # Generate not close matches
        print(f"Creating {NOT_CLOSE_COUNT} not close matches...")
        for i in range(NOT_CLOSE_COUNT):
            match = self.create_not_close_match(source_records[record_index])
            self.output_data.append(match)
            record_index += 1
            
        print(f"Generated {len(self.output_data)} total records")

    def save_test_data(self, filename: str):
        """Save generated data to CSV"""
        fieldnames = ['SOURCE_PKEY', 'NAME', 'SOURCE_SYSTEM', 'ADDRESS_LINE_1', 
                     'ADDRESS_LINE_2', 'CITY', 'STATE', 'POSTAL_CODE', 'COUNTRY']
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.output_data)
        
        print(f"Saved {len(self.output_data)} records to {filename}")

def main():
    """Main execution function"""
    random.seed(42)  # For reproducible results
    
    generator = TestDataGenerator()
    generator.load_valid_data('valid.csv')
    generator.generate_test_data()
    generator.save_test_data('test_matches.csv')
    
    # Print summary
    print("\n=== GENERATION SUMMARY ===")
    print(f"Exact matches: {EXACT_MATCH_COUNT} ({EXACT_MATCH_COUNT/TOTAL_RECORDS*100:.1f}%)")
    print(f"Very close matches: {VERY_CLOSE_COUNT} ({VERY_CLOSE_COUNT/TOTAL_RECORDS*100:.1f}%)")
    print(f"Somewhat close matches: {SOMEWHAT_CLOSE_COUNT} ({SOMEWHAT_CLOSE_COUNT/TOTAL_RECORDS*100:.1f}%)")
    print(f"Not close matches: {NOT_CLOSE_COUNT} ({NOT_CLOSE_COUNT/TOTAL_RECORDS*100:.1f}%)")
    print(f"Total: {TOTAL_RECORDS} records")

if __name__ == '__main__':
    main()