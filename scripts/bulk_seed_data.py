"""Bulk-populate every table with realistic-looking data for demo/testing.

Run: python scripts/bulk_seed_data.py

Idempotent-ish: safe to re-run, but will keep adding more rows on top of
whatever already exists (except the singleton Business/LoyaltyProgram rows).
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, time
from decimal import Decimal

from app import create_app
from app.extensions import db, bcrypt
from app.models.business import Business
from app.models.branch import Branch
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.sequence import Sequence
from app.models.medicine import Medicine, MedicineCategory, MedicineBatch
from app.models.stock_adjustment import StockAdjustment, StockAdjustmentItem
from app.models.supplier import Supplier
from app.models.purchase import PurchaseOrder, PurchaseOrderItem, Purchase, PurchaseItem
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.prescription import Prescription, PrescriptionItem
from app.models.sales import Sale, SaleItem, SalesReturn, SalesReturnItem
from app.models.compliance import ComplianceRecord
from app.models.drug_interaction import DrugInteraction
from app.models.gst import GstTransaction
from app.models.accounting import ChartOfAccount, JournalEntry, JournalEntryLine
from app.models.notification import Notification
from app.models.loyalty import LoyaltyProgram, LoyaltyTransaction
from app.models.purchase_return import PurchaseReturn, PurchaseReturnItem
from app.models.whatsapp_log import WhatsappLog
from app.models.ai_chat_log import AiChatLog

random.seed(42)

FIRST_NAMES = ['Ramesh', 'Suresh', 'Mahesh', 'Rajesh', 'Deepak', 'Anil', 'Sunil', 'Vijay', 'Ajay', 'Sanjay',
               'Priya', 'Pooja', 'Neha', 'Kavita', 'Sunita', 'Anita', 'Meena', 'Rekha', 'Geeta', 'Seema',
               'Amit', 'Rohit', 'Mohit', 'Nikhil', 'Rahul', 'Vikram', 'Arjun', 'Karan', 'Varun', 'Gaurav',
               'Sneha', 'Shweta', 'Divya', 'Swati', 'Preeti', 'Ritu', 'Nisha', 'Jyoti', 'Manju', 'Usha']
LAST_NAMES = ['Sharma', 'Verma', 'Gupta', 'Singh', 'Kumar', 'Patel', 'Shah', 'Joshi', 'Mehta', 'Yadav',
              'Rao', 'Reddy', 'Nair', 'Iyer', 'Chopra', 'Malhotra', 'Kapoor', 'Bhatt', 'Desai', 'Agarwal']
CITIES = [('Mumbai', 'Maharashtra', '400001'), ('Pune', 'Maharashtra', '411001'), ('Thane', 'Maharashtra', '400601'),
          ('Nagpur', 'Maharashtra', '440001'), ('Nashik', 'Maharashtra', '422001')]

def rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def rand_phone():
    return f"9{random.randint(100000000, 999999999)}"

def rand_date(start_days_ago, end_days_ago=0):
    d = random.randint(end_days_ago, start_days_ago)
    return date.today() - timedelta(days=d)

def rand_datetime(start_days_ago, end_days_ago=0):
    d = rand_date(start_days_ago, end_days_ago)
    return datetime.combine(d, datetime.min.time()) + timedelta(hours=random.randint(9, 20), minutes=random.randint(0, 59))


app = create_app('development')

with app.app_context():
    # ── Business (singleton) ──────────────────────────────────────────────
    biz = Business.query.first()
    if not biz:
        biz = Business(
            name="Sai Medical Store", legal_name="Sai Medical Store Pvt Ltd", short_name="Sai Medical",
            email="sai.medical@gmail.com", phone="9876543210",
            gstin="27AAPFU0939F1ZV", pan="AAPFU0939F", drug_license_no="MH-MUM-123456", fssai_no="10015043000123",
            address_line1="Shop No 12, MG Road", city="Mumbai", state="Maharashtra", pincode="400001",
            setup_complete=True, is_gst_registered=True,
        )
        db.session.add(biz)
        db.session.flush()
    bid = biz.id
    print(f"Business: {biz.name} (id={bid})")

    # ── Branches (target 4) ───────────────────────────────────────────────
    existing_branches = Branch.query.filter_by(business_id=bid).all()
    branch_names = [("Main Branch", "BR001", True), ("Andheri Branch", "BR002", False),
                     ("Thane Branch", "BR003", False), ("Pune Branch", "BR004", False)]
    for name, code, is_hq in branch_names:
        if not Branch.query.filter_by(code=code).first():
            city, state, pin = random.choice(CITIES)
            db.session.add(Branch(
                business_id=bid, name=name, code=code, is_headquarters=is_hq, is_active=True,
                phone=rand_phone(), email=f"{code.lower()}@saimedical.com",
                address_line1=f"Shop No {random.randint(1,50)}, Market Road", city=city, state=state, pincode=pin,
                manager_name=rand_name(), manager_phone=rand_phone(),
                opening_time=time(9, 0), closing_time=time(21, 30),
            ))
    db.session.commit()
    branches = Branch.query.filter_by(business_id=bid).all()
    print(f"Branches: {len(branches)}")

    # ── Users (target 50) ─────────────────────────────────────────────────
    roles_pool = ['pharmacist', 'cashier', 'store_manager', 'inventory_manager', 'accountant', 'doctor', 'viewer']
    existing_usernames = {u.username for u in User.query.all()}
    users_to_add = 50 - User.query.count()
    for i in range(max(0, users_to_add)):
        uname = f"staff{i+1}_{random.randint(100,999)}"
        while uname in existing_usernames:
            uname = f"staff{i+1}_{random.randint(100,999)}"
        existing_usernames.add(uname)
        fname = rand_name()
        u = User(
            branch_id=random.choice(branches).id, username=uname, full_name=fname,
            email=f"{uname}@saimedical.com", phone=rand_phone(), role=random.choice(roles_pool),
            is_active=random.random() > 0.05, designation=random.choice(['Senior Pharmacist', 'Cashier', 'Store Assistant', 'Manager']),
            created_at=rand_datetime(400, 1),
        )
        u.set_password("Staff@123")
        db.session.add(u)
    db.session.commit()
    users = User.query.all()
    print(f"Users: {len(users)}")

    # ── Medicine Categories ────────────────────────────────────────────────
    cat_names = ['Analgesic', 'Antibiotic', 'Antidiabetic', 'Cardiac', 'Antidepressant', 'Vitamin', 'Antacid',
                 'Antihistamine', 'Antiseptic', 'Dermatology', 'Ophthalmic', 'Respiratory', 'Gastrointestinal',
                 'Neurology', 'Gynaecology', 'Paediatric', 'Orthopaedic', 'ENT', 'Ayurvedic', 'Nutraceutical']
    existing_cats = {c.name for c in MedicineCategory.query.filter_by(business_id=bid).all()}
    for name in cat_names:
        if name not in existing_cats:
            db.session.add(MedicineCategory(business_id=bid, name=name))
    db.session.commit()
    categories = MedicineCategory.query.filter_by(business_id=bid).all()
    print(f"Medicine categories: {len(categories)}")

    # ── Suppliers (target 50) ──────────────────────────────────────────────
    supplier_companies = ['Sun Pharma', 'Cipla Ltd', 'Dr Reddy\'s Labs', 'Lupin Ltd', 'Mankind Pharma', 'Cadila Healthcare',
                          'Alkem Labs', 'Torrent Pharma', 'Glenmark Pharma', 'Aurobindo Pharma', 'Biocon Ltd', 'Ipca Labs',
                          'USV Pvt Ltd', 'Intas Pharma', 'Emcure Pharma', 'Wockhardt Ltd', 'Abbott India', 'GSK Pharma',
                          'Pfizer India', 'Novartis India', 'Zydus Lifesciences', 'Medley Pharma', 'Micro Labs',
                          'Ajanta Pharma', 'Unichem Labs', 'FDC Ltd', 'Indoco Remedies', 'Jubilant Pharmova',
                          'Natco Pharma', 'Strides Pharma']
    existing_supplier_names = {s.name for s in Supplier.query.filter_by(business_id=bid).all()}
    supplier_seq = Supplier.query.filter_by(business_id=bid).count()
    for name in supplier_companies:
        full_name = f"{name} Distributors"
        if full_name in existing_supplier_names:
            continue
        supplier_seq += 1
        city, state, _ = random.choice(CITIES)
        db.session.add(Supplier(
            business_id=bid, supplier_code=f"SUP-{supplier_seq:04d}", name=full_name,
            contact_person=rand_name(), phone=rand_phone(), email=f"contact@{name.lower().replace(' ', '').replace(chr(39),'')}.com",
            gst_number=f"{random.randint(10,37)}AAACT{random.randint(1000,9999)}F1Z{random.randint(1,9)}",
            drug_license_no=f"{state[:2].upper()}-DL-{random.randint(10000,99999)}",
            address=f"Plot {random.randint(1,200)}, Industrial Area", city=city, state=state,
            payment_terms=random.choice([15, 30, 45, 60]), credit_limit=Decimal(random.randint(50000, 500000)),
            outstanding=Decimal(random.randint(0, 80000)), performance_score=Decimal(str(round(random.uniform(2.5, 5.0), 1))),
            is_active=True,
        ))
    while supplier_seq < 50:
        supplier_seq += 1
        city, state, _ = random.choice(CITIES)
        db.session.add(Supplier(
            business_id=bid, supplier_code=f"SUP-{supplier_seq:04d}", name=f"Generic Pharma Distributors {supplier_seq}",
            contact_person=rand_name(), phone=rand_phone(), email=f"contact{supplier_seq}@pharma.com",
            gst_number=f"{random.randint(10,37)}AAACT{random.randint(1000,9999)}F1Z{random.randint(1,9)}",
            drug_license_no=f"{state[:2].upper()}-DL-{random.randint(10000,99999)}",
            address=f"Plot {random.randint(1,200)}, Industrial Area", city=city, state=state,
            payment_terms=random.choice([15, 30, 45, 60]), credit_limit=Decimal(random.randint(50000, 500000)),
            outstanding=Decimal(random.randint(0, 80000)), performance_score=Decimal(str(round(random.uniform(2.5, 5.0), 1))),
            is_active=True,
        ))
    db.session.commit()
    suppliers = Supplier.query.filter_by(business_id=bid).all()
    print(f"Suppliers: {len(suppliers)}")

    # ── Doctors (target 50) ────────────────────────────────────────────────
    specializations = ['Cardiology', 'General Physician', 'Dermatology', 'Orthopaedics', 'Paediatrics', 'Gynaecology',
                        'ENT', 'Neurology', 'Psychiatry', 'Endocrinology', 'Gastroenterology', 'Pulmonology', 'Urology']
    doc_count = Doctor.query.filter_by(business_id=bid).count()
    for i in range(doc_count, 50):
        db.session.add(Doctor(
            business_id=bid, doctor_code=f"DOC-{i+1:04d}", full_name=f"Dr. {rand_name()}",
            specialization=random.choice(specializations), qualification=random.choice(['MBBS', 'MD', 'MS', 'MBBS, MD', 'DNB']),
            registration_no=f"MH-{random.randint(10000,99999)}", phone=rand_phone(), email=f"dr.{i+1}@clinic.com",
            clinic_name=f"{random.choice(['City', 'Care', 'Life', 'Sunrise', 'Apollo'])} Clinic", is_active=True,
        ))
    db.session.commit()
    doctors = Doctor.query.filter_by(business_id=bid).all()
    print(f"Doctors: {len(doctors)}")

    # ── Patients (target 60) ───────────────────────────────────────────────
    pat_count = Patient.query.filter_by(business_id=bid).count()
    for i in range(pat_count, 60):
        db.session.add(Patient(
            business_id=bid, patient_code=f"PAT-{i+1:04d}", full_name=rand_name(),
            phone=rand_phone(), email=f"patient{i+1}@example.com", dob=rand_date(25000, 6000),
            gender=random.choice(['male', 'female']), address=f"House {random.randint(1,300)}, {random.choice(CITIES)[0]}",
            blood_group=random.choice(['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']),
            loyalty_points=random.randint(0, 500), total_purchases=Decimal(random.randint(0, 20000)),
            loyalty_tier=random.choice(['silver', 'silver', 'gold', 'platinum']),
            is_active=True, created_at=rand_datetime(500, 1),
        ))
    db.session.commit()
    patients = Patient.query.filter_by(business_id=bid).all()
    print(f"Patients: {len(patients)}")

    # ── Medicines (target 60) ──────────────────────────────────────────────
    med_templates = [
        ("Paracetamol", "Crocin", "Analgesic", "OTC", 12), ("Amoxicillin", "Mox", "Antibiotic", "H", 12),
        ("Metformin", "Glycomet", "Antidiabetic", "H", 12), ("Atorvastatin", "Lipitor", "Cardiac", "H", 12),
        ("Alprazolam", "Alprax", "Antidepressant", "X", 12), ("Omeprazole", "Omez", "Antacid", "H", 12),
        ("Cholecalciferol", "D3-Must", "Vitamin", "OTC", 12), ("Cetirizine", "Zyrtec", "Antihistamine", "OTC", 5),
        ("Azithromycin", "Azee", "Antibiotic", "H", 12), ("Pantoprazole", "Pan 40", "Antacid", "H", 12),
        ("Ibuprofen", "Brufen", "Analgesic", "OTC", 12), ("Diclofenac", "Voveran", "Analgesic", "H", 12),
        ("Amlodipine", "Amlong", "Cardiac", "H", 12), ("Losartan", "Losar", "Cardiac", "H", 12),
        ("Metoprolol", "Betaloc", "Cardiac", "H", 12), ("Levothyroxine", "Eltroxin", "Endocrine", "H", 5),
        ("Ciprofloxacin", "Ciplox", "Antibiotic", "H", 12), ("Doxycycline", "Doxy", "Antibiotic", "H", 12),
        ("Salbutamol", "Asthalin", "Respiratory", "H", 12), ("Montelukast", "Montair", "Respiratory", "H", 12),
        ("Ranitidine", "Rantac", "Antacid", "OTC", 12), ("Domperidone", "Domstal", "Gastrointestinal", "OTC", 12),
        ("Ondansetron", "Emeset", "Gastrointestinal", "H", 12), ("Multivitamin", "Revital", "Vitamin", "OTC", 18),
        ("Calcium Carbonate", "Shelcal", "Vitamin", "OTC", 12), ("Iron+Folic Acid", "Autrin", "Vitamin", "OTC", 12),
        ("Loratadine", "Lorfast", "Antihistamine", "OTC", 5), ("Fexofenadine", "Allegra", "Antihistamine", "OTC", 5),
        ("Clopidogrel", "Clopilet", "Cardiac", "H", 12), ("Aspirin", "Ecosprin", "Cardiac", "OTC", 5),
        ("Insulin Glargine", "Lantus", "Antidiabetic", "H1", 5), ("Glimepiride", "Amaryl", "Antidiabetic", "H", 12),
        ("Sertraline", "Zoloft", "Antidepressant", "H1", 12), ("Escitalopram", "Nexito", "Antidepressant", "H1", 12),
        ("Diazepam", "Valium", "Antidepressant", "X", 12), ("Tramadol", "Ultram", "Analgesic", "H1", 12),
        ("Morphine", "Morcontin", "Analgesic", "X", 12), ("Codeine", "Codeine Syrup", "Analgesic", "X", 12),
        ("Hydrochlorothiazide", "Aquazide", "Cardiac", "H", 12), ("Furosemide", "Lasix", "Cardiac", "H", 12),
        ("Prednisolone", "Wysolone", "Dermatology", "H", 12), ("Betamethasone Cream", "Betnovate", "Dermatology", "H", 12),
        ("Clotrimazole Cream", "Candid", "Dermatology", "OTC", 12), ("Mupirocin Ointment", "T-Bact", "Dermatology", "H", 12),
        ("Ofloxacin Eye Drop", "Exocin", "Ophthalmic", "H", 12), ("Timolol Eye Drop", "Timolet", "Ophthalmic", "H", 12),
        ("ORS Powder", "Electral", "Gastrointestinal", "OTC", 5), ("Zinc Sulphate", "Zincovit", "Vitamin", "OTC", 12),
        ("Amoxiclav", "Augmentin", "Antibiotic", "H", 12), ("Cefixime", "Taxim-O", "Antibiotic", "H", 12),
        ("Vitamin B Complex", "Becosules", "Vitamin", "OTC", 12), ("Folic Acid", "Folvite", "Vitamin", "OTC", 12),
        ("Rabeprazole", "Rablet", "Antacid", "H", 12), ("Esomeprazole", "Nexpro", "Antacid", "H", 12),
        ("Chlorpheniramine", "Piriton", "Antihistamine", "OTC", 5), ("Hydroxyzine", "Atarax", "Antihistamine", "H", 12),
        ("Nitrofurantoin", "Furadantin", "Antibiotic", "H", 12), ("Metronidazole", "Flagyl", "Antibiotic", "OTC", 12),
        ("Ashwagandha", "Himalaya Ashwagandha", "Ayurvedic", "OTC", 18), ("Chyawanprash", "Dabur Chyawanprash", "Ayurvedic", "OTC", 18),
    ]
    manufacturers = ['GSK', 'Cipla', 'USV', 'Pfizer', "Sun Pharma", "Dr Reddy's", 'Mankind', 'Alkem', 'Torrent', 'Lupin']
    med_count = Medicine.query.filter_by(business_id=bid).count()
    cat_by_name = {c.name: c.id for c in categories}
    idx = med_count
    for generic, brand, cat_name, sched, gst in med_templates[med_count:60]:
        idx += 1
        mrp = random.randint(15, 500)
        pr = round(mrp * 0.65)
        sr = round(mrp * 0.85)
        db.session.add(Medicine(
            business_id=bid, medicine_code=f"MED-{idx:04d}", name=f"{generic} {random.choice([250,500,650,10,20])}mg",
            generic_name=generic, brand_name=brand, salt_composition=f"{generic} salt composition",
            category_id=cat_by_name.get(cat_name), manufacturer=random.choice(manufacturers),
            hsn_code=str(random.choice([30049099, 30041020, 30045090])), schedule_type=sched,
            gst_rate=Decimal(str(gst)), mrp=Decimal(mrp), purchase_rate=Decimal(pr), selling_rate=Decimal(sr),
            barcode=f"890{random.randint(1000000000, 9999999999)}"[:13],
            rack_location=f"R{random.randint(1,20)}", storage_condition=random.choice(['room_temp', 'room_temp', 'refrigerated']),
            prescription_req=(sched in ('H', 'H1', 'X')), narcotic_flag=(sched == 'X'),
            reorder_level=random.randint(10, 30), max_stock_level=random.randint(300, 800), is_active=True,
        ))
    db.session.commit()
    medicines = Medicine.query.filter_by(business_id=bid).all()
    print(f"Medicines: {len(medicines)}")

    # ── Medicine Batches (target ~150, several per medicine) ───────────────
    batch_count = MedicineBatch.query.count()
    target_batches = 150
    if batch_count < target_batches:
        for i in range(batch_count, target_batches):
            med = random.choice(medicines)
            branch = random.choice(branches)
            exp = date.today() + timedelta(days=random.randint(-30, 720))
            qty = random.randint(0, 300)
            db.session.add(MedicineBatch(
                medicine_id=med.id, branch_id=branch.id, batch_number=f"B{med.id:04d}{i:03d}",
                mfg_date=exp - timedelta(days=730), expiry_date=exp, quantity=qty,
                reserved_qty=0, purchase_rate=med.purchase_rate, mrp=med.mrp, selling_rate=med.selling_rate,
                rack_location=med.rack_location, is_expired=(exp < date.today()), is_damaged=(random.random() < 0.03),
                created_at=rand_datetime(300, 1),
                # Old updated_at on ~half the batches feeds the non-moving/dead-stock reports.
                updated_at=rand_datetime(300, 1) if random.random() < 0.5 else datetime.now(),
            ))
    db.session.commit()
    batches = MedicineBatch.query.all()
    print(f"Medicine batches: {len(batches)}")

    # ── Drug Interactions (target 50) ───────────────────────────────────────
    generics = list({m.generic_name for m in medicines if m.generic_name})
    di_count = DrugInteraction.query.count()
    severities = ['minor', 'moderate', 'major', 'contraindicated']
    tried = set()
    while DrugInteraction.query.count() < 50 and len(tried) < 500:
        a, b = random.sample(generics, 2)
        key = tuple(sorted([a, b]))
        if key in tried:
            continue
        tried.add(key)
        if DrugInteraction.query.filter_by(drug_a_generic=a, drug_b_generic=b).first():
            continue
        db.session.add(DrugInteraction(
            drug_a_generic=a, drug_b_generic=b, severity=random.choice(severities),
            description=f"Potential interaction between {a} and {b} — monitor patient response.",
            recommendation="Consult physician before co-administration.", source='Internal DB',
        ))
    db.session.commit()
    print(f"Drug interactions: {DrugInteraction.query.count()}")

    # ── Purchase Orders + Items (target 50) ─────────────────────────────────
    po_count = PurchaseOrder.query.filter_by(business_id=bid).count()
    for i in range(po_count, 50):
        supplier = random.choice(suppliers)
        branch = random.choice(branches)
        order_date = rand_date(200, 1)
        po = PurchaseOrder(
            business_id=bid, branch_id=branch.id, po_number=f"PO-{i+1:05d}", supplier_id=supplier.id,
            order_date=order_date, expected_date=order_date + timedelta(days=7),
            status=random.choice(['draft', 'sent', 'partial', 'received', 'received']),
            created_by=random.choice(users).id, created_at=datetime.combine(order_date, datetime.min.time()),
        )
        db.session.add(po)
        db.session.flush()
        total = Decimal(0)
        for _ in range(random.randint(2, 6)):
            med = random.choice(medicines)
            qty = random.randint(10, 100)
            rate = med.purchase_rate
            db.session.add(PurchaseOrderItem(po_id=po.id, medicine_id=med.id, quantity=qty, rate=rate))
            total += rate * qty
        po.total_amount = total
    db.session.commit()
    print(f"Purchase orders: {PurchaseOrder.query.filter_by(business_id=bid).count()}")

    # ── Purchases + Items (target 50) ───────────────────────────────────────
    purchase_count = Purchase.query.filter_by(business_id=bid).count()
    purchases_all = []
    for i in range(purchase_count, 50):
        supplier = random.choice(suppliers)
        branch = random.choice(branches)
        bill_date = rand_date(180, 1)
        subtotal = Decimal(0)
        cgst = sgst = Decimal(0)
        items_data = []
        for _ in range(random.randint(2, 6)):
            med = random.choice(medicines)
            qty = random.randint(10, 80)
            rate = med.purchase_rate
            gst_rate = med.gst_rate
            line_amt = rate * qty
            half = line_amt * gst_rate / 200
            subtotal += line_amt
            cgst += half
            sgst += half
            items_data.append((med, qty, rate, gst_rate, half))
        total = subtotal + cgst + sgst
        paid = total if random.random() > 0.3 else round(total * Decimal(random.choice(['0.5', '0.7', '0'])), 2)
        due = total - paid
        status = 'paid' if due <= 0 else ('partial' if paid > 0 else 'unpaid')
        purchase = Purchase(
            business_id=bid, branch_id=branch.id, bill_number=f"PB-{i+1:05d}", supplier_id=supplier.id,
            bill_date=bill_date, invoice_number=f"INV-SUP-{random.randint(1000,9999)}", invoice_date=bill_date,
            subtotal=subtotal, cgst_amount=cgst, sgst_amount=sgst, igst_amount=Decimal(0),
            total_amount=total, paid_amount=paid, due_amount=due,
            payment_mode=random.choice(['cash', 'bank_transfer', 'cheque', 'credit']), payment_status=status,
            created_by=random.choice(users).id, created_at=datetime.combine(bill_date, datetime.min.time()),
        )
        db.session.add(purchase)
        db.session.flush()
        for med, qty, rate, gst_rate, half in items_data:
            exp = date.today() + timedelta(days=random.randint(90, 700))
            pi = PurchaseItem(
                purchase_id=purchase.id, medicine_id=med.id, batch_number=f"PB{purchase.id}{med.id}",
                mfg_date=exp - timedelta(days=730), expiry_date=exp, quantity=qty, purchase_rate=rate,
                mrp=med.mrp, gst_rate=gst_rate, cgst_amount=half, sgst_amount=half,
                total_amount=(rate * qty) + (half * 2),
            )
            db.session.add(pi)
        purchases_all.append(purchase)
    db.session.commit()
    purchases = Purchase.query.filter_by(business_id=bid).all()
    print(f"Purchases: {len(purchases)}")

    # ── Purchase Returns + Items (target 50) ────────────────────────────────
    pr_count = PurchaseReturn.query.filter_by(business_id=bid).count()
    purchase_items_all = PurchaseItem.query.join(Purchase).filter(Purchase.business_id == bid).all()
    for i in range(pr_count, min(50, len(purchases))):
        purchase = purchases[i % len(purchases)]
        branch_id = purchase.branch_id
        pr = PurchaseReturn(
            business_id=bid, branch_id=branch_id, return_number=f"PRET-{i+1:05d}",
            original_purchase_id=purchase.id, supplier_id=purchase.supplier_id,
            return_date=purchase.bill_date + timedelta(days=random.randint(1, 20)),
            reason=random.choice(['Damaged in transit', 'Expired stock', 'Wrong item supplied', 'Excess quantity']),
            total_amount=Decimal(random.randint(500, 5000)),
            status=random.choice(['pending', 'sent', 'credited']),
        )
        db.session.add(pr)
        db.session.flush()
        matching_batch = next((b for b in batches if b.purchase_item_id in [pi.id for pi in purchase.items]), None) or random.choice(batches)
        for item in purchase.items[:2]:
            qty = min(item.quantity, random.randint(1, 5))
            db.session.add(PurchaseReturnItem(
                return_id=pr.id, medicine_id=item.medicine_id, batch_id=matching_batch.id,
                quantity=qty, rate=item.purchase_rate, amount=item.purchase_rate * qty,
            ))
    db.session.commit()
    print(f"Purchase returns: {PurchaseReturn.query.filter_by(business_id=bid).count()}")

    # ── Sales + Items (target 60) ───────────────────────────────────────────
    sale_count = Sale.query.filter_by(business_id=bid).count()
    for i in range(sale_count, 60):
        branch = random.choice(branches)
        patient = random.choice(patients) if random.random() > 0.2 else None
        cashier = random.choice(users)
        invoice_date = rand_datetime(200, 0)
        subtotal = Decimal(0)
        cgst = sgst = Decimal(0)
        items_data = []
        available_batches = [b for b in batches if b.quantity > 0 and not b.is_expired]
        if not available_batches:
            break
        for _ in range(random.randint(1, 5)):
            batch = random.choice(available_batches)
            med = next((m for m in medicines if m.id == batch.medicine_id), None)
            if not med:
                continue
            qty = min(random.randint(1, 5), max(1, batch.quantity))
            rate = batch.selling_rate or med.selling_rate
            gst_rate = med.gst_rate
            line_amt = rate * qty
            half = line_amt * gst_rate / 200
            subtotal += line_amt
            cgst += half
            sgst += half
            items_data.append((med, batch, qty, rate, gst_rate, half))
        if not items_data:
            continue
        total = subtotal + cgst + sgst
        pay_mode = random.choice(['cash', 'card', 'upi', 'credit'])
        # Credit sales are only partly paid so the credit-outstanding report has rows.
        paid = (total * Decimal(random.choice([0, 25, 50])) / 100).quantize(Decimal('0.01')) if pay_mode == 'credit' else total
        seq_code, _ = Sequence.next_number(f'invoice-{bid}-{invoice_date.year}-bulk', prefix=f'BINV-{invoice_date.year}-', pad=5)
        sale = Sale(
            business_id=bid, branch_id=branch.id, invoice_number=seq_code, patient_id=patient.id if patient else None,
            invoice_date=invoice_date, cashier_id=cashier.id, subtotal=subtotal, cgst_amount=cgst, sgst_amount=sgst,
            igst_amount=Decimal(0), total_amount=total, paid_amount=paid,
            payment_mode=pay_mode, status='confirmed',
            created_at=invoice_date,
        )
        db.session.add(sale)
        db.session.flush()
        for med, batch, qty, rate, gst_rate, half in items_data:
            si = SaleItem(
                sale_id=sale.id, medicine_id=med.id, batch_id=batch.id, quantity=qty, mrp=med.mrp,
                selling_rate=rate, gst_rate=gst_rate, cgst_amount=half, sgst_amount=half,
                total_amount=(rate * qty) + (half * 2),
            )
            db.session.add(si)
            batch.quantity = max(0, batch.quantity - qty)
            if med.schedule_type in ('H', 'H1', 'X'):
                db.session.add(ComplianceRecord(
                    business_id=bid, branch_id=branch.id, record_type='schedule_h' if med.schedule_type == 'H' else ('schedule_h1' if med.schedule_type == 'H1' else 'narcotic'),
                    sale_id=sale.id, medicine_id=med.id, patient_id=patient.id if patient else None,
                    quantity_dispensed=qty, dispensed_date=invoice_date, dispensed_by=cashier.id, batch_number=batch.batch_number,
                ))
    db.session.commit()
    sales = Sale.query.filter_by(business_id=bid).all()
    print(f"Sales: {len(sales)}")

    # ── Sales Returns + Items (target 50) ───────────────────────────────────
    sr_count = SalesReturn.query.filter_by(business_id=bid).count()
    confirmed_sales = [s for s in sales if s.items]
    for i in range(sr_count, min(50, len(confirmed_sales))):
        sale = confirmed_sales[i % len(confirmed_sales)]
        sale_item = sale.items[0]
        sret = SalesReturn(
            business_id=bid, branch_id=sale.branch_id, return_number=f"SRET-{i+1:05d}",
            original_sale_id=sale.id, patient_id=sale.patient_id,
            return_date=sale.invoice_date + timedelta(days=random.randint(1, 10)),
            reason=random.choice(['Wrong medicine', 'Adverse reaction', 'Customer changed mind', 'Damaged pack']),
            total_refund=sale_item.total_amount, refund_mode=random.choice(['cash', 'card', 'credit_note']),
            processed_by=random.choice(users).id, status='processed',
        )
        db.session.add(sret)
        db.session.flush()
        db.session.add(SalesReturnItem(
            return_id=sret.id, sale_item_id=sale_item.id, medicine_id=sale_item.medicine_id,
            batch_id=sale_item.batch_id, quantity=sale_item.quantity, refund_amount=sale_item.total_amount,
        ))
    db.session.commit()
    print(f"Sales returns: {SalesReturn.query.filter_by(business_id=bid).count()}")

    # ── Prescriptions + Items (target 50) ───────────────────────────────────
    rx_count = Prescription.query.filter_by(business_id=bid).count()
    for i in range(rx_count, 50):
        patient = random.choice(patients)
        doctor = random.choice(doctors)
        branch = random.choice(branches)
        rx_date = rand_date(150, 1)
        rx = Prescription(
            business_id=bid, branch_id=branch.id, prescription_code=f"RX-{i+1:05d}", patient_id=patient.id,
            doctor_id=doctor.id, rx_date=rx_date, is_verified=random.random() > 0.3,
            validity_days=30, status=random.choice(['pending', 'verified', 'dispensed']),
            created_at=datetime.combine(rx_date, datetime.min.time()),
        )
        db.session.add(rx)
        db.session.flush()
        for _ in range(random.randint(1, 4)):
            med = random.choice(medicines)
            qty = random.randint(5, 30)
            db.session.add(PrescriptionItem(
                prescription_id=rx.id, medicine_id=med.id, generic_name=med.generic_name,
                dosage=f"{random.choice([1,2])} tablet {random.choice(['OD','BD','TDS'])}",
                duration=f"{random.choice([3,5,7,10,15])} days", quantity=qty, dispensed_qty=qty if rx.status == 'dispensed' else 0,
            ))
    db.session.commit()
    print(f"Prescriptions: {Prescription.query.filter_by(business_id=bid).count()}")

    # ── GST Transactions (target 50, derived from sales/purchases) ─────────
    gst_count = GstTransaction.query.filter_by(business_id=bid).count()
    src_sales = sales[:30]
    src_purchases = purchases[:20]
    for s in src_sales[gst_count:]:
        db.session.add(GstTransaction(
            business_id=bid, branch_id=s.branch_id, transaction_type='sale', reference_id=s.id,
            reference_type='sale', gstin=biz.gstin, transaction_date=s.invoice_date.date(),
            taxable_value=s.subtotal, cgst_amount=s.cgst_amount, sgst_amount=s.sgst_amount, igst_amount=s.igst_amount,
            fy=f"{s.invoice_date.year}-{str(s.invoice_date.year+1)[2:]}", period=s.invoice_date.strftime('%Y-%m'),
        ))
    for p in src_purchases:
        db.session.add(GstTransaction(
            business_id=bid, branch_id=p.branch_id, transaction_type='purchase', reference_id=p.id,
            reference_type='purchase', gstin=biz.gstin, transaction_date=p.bill_date,
            taxable_value=p.subtotal, cgst_amount=p.cgst_amount, sgst_amount=p.sgst_amount, igst_amount=p.igst_amount,
            fy=f"{p.bill_date.year}-{str(p.bill_date.year+1)[2:]}", period=p.bill_date.strftime('%Y-%m'),
        ))
    db.session.commit()
    print(f"GST transactions: {GstTransaction.query.filter_by(business_id=bid).count()}")

    # ── Chart of Accounts + Journal Entries (target 50 entries) ─────────────
    default_accounts = [
        ('1000', 'Cash', 'asset'), ('1010', 'Bank', 'asset'), ('1100', 'Accounts Receivable', 'asset'),
        ('1200', 'Inventory', 'asset'), ('2000', 'Accounts Payable', 'liability'), ('3000', 'Owner Equity', 'equity'),
        ('4000', 'Sales Revenue', 'revenue'), ('5000', 'Purchase Expense', 'expense'), ('5100', 'Operating Expense', 'expense'),
        ('5200', 'Rent Expense', 'expense'), ('5300', 'Salary Expense', 'expense'), ('5400', 'Utility Expense', 'expense'),
    ]
    if not ChartOfAccount.query.filter_by(business_id=bid).first():
        for code, name, acc_type in default_accounts:
            db.session.add(ChartOfAccount(business_id=bid, code=code, name=name, type=acc_type, is_system=True))
        db.session.commit()
    accounts = ChartOfAccount.query.filter_by(business_id=bid).all()
    cash_acc = next(a for a in accounts if a.code == '1000')
    revenue_acc = next(a for a in accounts if a.code == '4000')
    expense_accs = [a for a in accounts if a.type == 'expense']

    je_count = JournalEntry.query.filter_by(business_id=bid).count()
    for i in range(je_count, 50):
        entry_date = rand_date(150, 1)
        amount = Decimal(random.randint(500, 20000))
        expense_acc = random.choice(expense_accs)
        entry_code, _ = Sequence.next_number(f'journal-{bid}-bulk', prefix='BJE-', pad=5)
        je = JournalEntry(
            business_id=bid, branch_id=random.choice(branches).id, entry_number=entry_code, entry_date=entry_date,
            narration=f"{expense_acc.name} payment", total_debit=amount, total_credit=amount,
            created_by=random.choice(users).id, created_at=datetime.combine(entry_date, datetime.min.time()),
        )
        db.session.add(je)
        db.session.flush()
        db.session.add(JournalEntryLine(entry_id=je.id, account_id=expense_acc.id, debit=amount, credit=0))
        db.session.add(JournalEntryLine(entry_id=je.id, account_id=cash_acc.id, debit=0, credit=amount))
    db.session.commit()
    print(f"Journal entries: {JournalEntry.query.filter_by(business_id=bid).count()}")

    # ── Notifications (target 50) ───────────────────────────────────────────
    notif_types = ['expiry', 'reorder', 'low_stock', 'dead_stock', 'payment_due', 'license_expiry', 'system']
    notif_count = Notification.query.filter_by(business_id=bid).count()
    for i in range(notif_count, 50):
        med = random.choice(medicines)
        ntype = random.choice(notif_types)
        db.session.add(Notification(
            business_id=bid, branch_id=random.choice(branches).id, user_id=random.choice(users).id, type=ntype,
            title=f"{ntype.replace('_',' ').title()} Alert", message=f"Alert regarding {med.name}: {ntype.replace('_',' ')} threshold reached.",
            reference_type='medicine', reference_id=med.id, is_read=random.random() > 0.4,
            priority=random.choice(['low', 'medium', 'high', 'critical']),
            created_at=rand_datetime(60, 0),
        ))
    db.session.commit()
    print(f"Notifications: {Notification.query.filter_by(business_id=bid).count()}")

    # ── Loyalty Program (singleton) + Transactions (target 50) ─────────────
    program = LoyaltyProgram.query.filter_by(business_id=bid).first()
    if not program:
        program = LoyaltyProgram(business_id=bid)
        db.session.add(program)
        db.session.commit()
    lt_count = LoyaltyTransaction.query.count()
    for i in range(lt_count, 50):
        patient = random.choice(patients)
        points = random.randint(5, 200)
        db.session.add(LoyaltyTransaction(
            patient_id=patient.id, type=random.choice(['earn', 'redeem', 'cashback', 'referral']),
            points=points, balance=patient.loyalty_points or points,
            notes="Bulk demo transaction", created_at=rand_datetime(120, 0),
        ))
    db.session.commit()
    print(f"Loyalty transactions: {LoyaltyTransaction.query.count()}")

    # ── Stock Adjustments + Items (target 50) ───────────────────────────────
    sa_count = StockAdjustment.query.filter_by(business_id=bid).count()
    adj_types = ['damage', 'expiry', 'correction', 'audit']
    for i in range(sa_count, 50):
        branch = random.choice(branches)
        adj = StockAdjustment(
            business_id=bid, branch_id=branch.id, adj_number=f"ADJ-{i+1:05d}", adj_type=random.choice(adj_types),
            reason="Routine stock audit adjustment", adjusted_by=random.choice(users).id,
            status=random.choice(['pending', 'approved']), created_at=rand_datetime(100, 0),
        )
        db.session.add(adj)
        db.session.flush()
        batch = random.choice(batches)
        change = random.choice([-5, -3, -1, 1, 2])
        db.session.add(StockAdjustmentItem(
            adjustment_id=adj.id, batch_id=batch.id, medicine_id=batch.medicine_id,
            qty_before=batch.quantity, qty_change=change, qty_after=max(0, batch.quantity + change),
            reason=adj.reason,
        ))
    db.session.commit()
    print(f"Stock adjustments: {StockAdjustment.query.filter_by(business_id=bid).count()}")

    # ── Audit Logs (target 50) ──────────────────────────────────────────────
    actions = ['login', 'logout', 'create', 'update', 'delete', 'export', 'view']
    modules = ['sales', 'purchase', 'inventory', 'medicines', 'patients', 'accounting', 'security']
    while AuditLog.query.count() < 50:
        AuditLog.log(
            action=random.choice(actions), module=random.choice(modules),
            description="Bulk demo audit entry", user_id=random.choice(users).id,
            ip_address="127.0.0.1", severity=random.choice(['info', 'warning']),
        )
    db.session.commit()
    print(f"Audit logs: {AuditLog.query.count()}")

    # ── WhatsApp Logs (target 50) ───────────────────────────────────────────
    wa_count = WhatsappLog.query.filter_by(business_id=bid).count()
    for i in range(wa_count, 50):
        patient = random.choice(patients)
        db.session.add(WhatsappLog(
            business_id=bid, patient_id=patient.id, to_number=patient.phone or rand_phone(),
            message_type=random.choice(['invoice', 'payment_reminder', 'prescription_reminder', 'refill_reminder', 'promotional']),
            message_body="Demo WhatsApp message body.", status=random.choice(['sent', 'queued', 'failed']),
            sent_by=random.choice(users).id, created_at=rand_datetime(90, 0),
        ))
    db.session.commit()
    print(f"WhatsApp logs: {WhatsappLog.query.filter_by(business_id=bid).count()}")

    # ── AI Chat Logs (target 50) ────────────────────────────────────────────
    sample_questions = ["low stock", "sales today", "stock of Paracetamol", "reorder", "expiry"]
    ai_count = AiChatLog.query.filter_by(business_id=bid).count()
    for i in range(ai_count, 50):
        db.session.add(AiChatLog(
            business_id=bid, user_id=random.choice(users).id, question=random.choice(sample_questions),
            answer="Demo answer from rule-based assistant.", intent=random.choice(['stock_query', 'low_stock', 'sales_query', 'reorder_query']),
            created_at=rand_datetime(60, 0),
        ))
    db.session.commit()
    print(f"AI chat logs: {AiChatLog.query.filter_by(business_id=bid).count()}")

    print("\n✅ Bulk seed complete.")
