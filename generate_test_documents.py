"""
Generate mock medical documents (PDFs and images) for all 12 test cases.

Produces documents in test_documents/ organized by test case ID.
Some documents are intentionally degraded (blur, noise) to test quality handling.

Requirements:
    pip install fpdf2 opencv-python-headless numpy Pillow
"""

import os
import json
import numpy as np
import cv2
from fpdf import FPDF
from PIL import Image

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "test_documents")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


# --- PDF Generators ---


def make_prescription_pdf(path, *, doctor_name, doctor_reg="", patient_name="",
                          date="", diagnosis="", medicines=None, tests_ordered=None,
                          treatment="", clinic_name="City Medical Centre"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, doctor_name, ln=True)
    pdf.set_font("Helvetica", "", 10)
    if doctor_reg:
        pdf.cell(0, 6, f"Reg. No: {doctor_reg}", ln=True)
    pdf.cell(0, 6, clinic_name, ln=True)
    pdf.cell(0, 6, "Ph: +91-80-XXXXXXXX", ln=True)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 11)
    if patient_name:
        pdf.cell(0, 6, f"Patient: {patient_name}", ln=True)
    if date:
        pdf.cell(0, 6, f"Date: {date}", ln=True)
    pdf.ln(3)

    if diagnosis:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, f"Diagnosis: {diagnosis}", ln=True)
    if treatment:
        pdf.cell(0, 6, f"Treatment: {treatment}", ln=True)
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 11)
    if medicines:
        pdf.cell(0, 6, "Rx:", ln=True)
        for i, med in enumerate(medicines, 1):
            pdf.cell(0, 6, f"  {i}. {med}", ln=True)
    if tests_ordered:
        pdf.ln(2)
        pdf.cell(0, 6, "Investigations:", ln=True)
        for t in tests_ordered:
            pdf.cell(0, 6, f"  - {t}", ln=True)

    pdf.ln(10)
    pdf.cell(0, 6, "[Doctor's Signature & Stamp]", ln=True, align="R")
    pdf.output(path)


def make_hospital_bill_pdf(path, *, hospital_name="City Clinic", patient_name="",
                           date="", line_items=None, total=0):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, hospital_name, ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "GSTIN: 29XXXXX1234X1ZX", ln=True, align="C")
    pdf.ln(4)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "BILL / RECEIPT", ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    if patient_name:
        pdf.cell(0, 6, f"Patient: {patient_name}", ln=True)
    if date:
        pdf.cell(0, 6, f"Date: {date}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(100, 6, "DESCRIPTION")
    pdf.cell(30, 6, "AMOUNT (INR)", ln=True, align="R")
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.set_font("Helvetica", "", 10)

    if line_items:
        for item in line_items:
            desc = item.get("description", "")
            amt = item.get("amount", 0)
            pdf.cell(100, 6, desc)
            pdf.cell(30, 6, f"{amt:,.2f}", ln=True, align="R")

    pdf.ln(2)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(100, 8, "TOTAL:")
    pdf.cell(30, 8, f"{total:,.2f}", ln=True, align="R")

    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Payment Mode: Cash / UPI", ln=True)
    pdf.cell(0, 6, "[Cashier Stamp]", ln=True)
    pdf.output(path)


def make_pharmacy_bill_pdf(path, *, patient_name="", doctor_name="", date="",
                           medicines=None, total=0):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "HEALTH FIRST PHARMACY", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Drug Lic. No: KA-BLR-XXXX", ln=True, align="C")
    pdf.cell(0, 6, "22 Brigade Road, Bengaluru", ln=True, align="C")
    pdf.ln(4)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    if patient_name:
        pdf.cell(0, 6, f"Patient: {patient_name}    Dr: {doctor_name}", ln=True)
    if date:
        pdf.cell(0, 6, f"Date: {date}", ln=True)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 6, "MEDICINE")
    pdf.cell(20, 6, "QTY")
    pdf.cell(25, 6, "MRP")
    pdf.cell(25, 6, "AMT", ln=True)
    pdf.set_font("Helvetica", "", 10)

    if medicines:
        for med in medicines:
            name = med.get("name", "")
            qty = med.get("qty", 1)
            mrp = med.get("mrp", 0)
            amt = med.get("amount", mrp * qty)
            pdf.cell(60, 6, name)
            pdf.cell(20, 6, str(qty))
            pdf.cell(25, 6, f"{mrp:.2f}")
            pdf.cell(25, 6, f"{amt:.2f}", ln=True)

    pdf.ln(2)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(100, 8, "Net Amount:")
    pdf.cell(30, 8, f"{total:,.2f}", ln=True, align="R")
    pdf.output(path)


def make_lab_report_pdf(path, *, patient_name="", doctor_name="", date="",
                        test_name="", results=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "PRECISION DIAGNOSTICS PVT LTD", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "NABL Accredited | Lab ID: KA-NABL-1234", ln=True, align="C")
    pdf.ln(4)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    if patient_name:
        pdf.cell(0, 6, f"Patient: {patient_name}", ln=True)
    if doctor_name:
        pdf.cell(0, 6, f"Ref Doctor: {doctor_name}", ln=True)
    if date:
        pdf.cell(0, 6, f"Report Date: {date}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, f"Test: {test_name}", ln=True)
    pdf.ln(2)

    if results:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(50, 6, "Parameter")
        pdf.cell(30, 6, "Result")
        pdf.cell(30, 6, "Normal Range", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for r in results:
            pdf.cell(50, 6, r.get("param", ""))
            pdf.cell(30, 6, r.get("result", ""))
            pdf.cell(30, 6, r.get("range", ""), ln=True)

    pdf.ln(6)
    pdf.cell(0, 6, "Dr. Meena Pillai, MD (Pathology)", ln=True)
    pdf.cell(0, 6, "[Signature & Stamp]", ln=True)
    pdf.output(path)


# --- Image Degradation ---


def pdf_to_image(pdf_path):
    """Convert first page of PDF to image using PIL (reads raw bytes as proxy)."""
    # Since we can't use poppler/ghostscript reliably, generate a rendered image
    # by creating the document directly as an image instead.
    # This function is a fallback — we generate .jpg files directly for degraded docs.
    pass


def apply_blur(image_path, output_path, kernel_size=5):
    img = cv2.imread(image_path)
    blurred = cv2.GaussianBlur(img, (kernel_size, kernel_size), 0)
    cv2.imwrite(output_path, blurred)


def apply_heavy_degradation(image_path, output_path):
    """Poor quality photo — text is partially readable but some fields are ambiguous."""
    img = cv2.imread(image_path)
    blurred = cv2.GaussianBlur(img, (5, 5), 0)
    noise = np.random.normal(0, 5, img.shape).astype(np.uint8)
    degraded = cv2.add(blurred, noise)
    cv2.imwrite(output_path, degraded)


def apply_moderate_degradation(image_path, output_path):
    """Degraded phone photo — blur + compression + contrast loss. Targets DEGRADED (0.2-0.7) OCR score."""
    img = cv2.imread(image_path)
    blurred = cv2.GaussianBlur(img, (3, 3), 1.0)
    degraded = cv2.convertScaleAbs(blurred, alpha=0.8, beta=30)
    cv2.imwrite(output_path, degraded, [cv2.IMWRITE_JPEG_QUALITY, 40])


def apply_light_degradation(image_path, output_path):
    """Phone photo quality — slight blur, readable but not crisp."""
    img = cv2.imread(image_path)
    blurred = cv2.GaussianBlur(img, (3, 3), 0)
    noise = np.random.normal(0, 5, img.shape).astype(np.uint8)
    degraded = cv2.add(blurred, noise)
    cv2.imwrite(output_path, degraded)


def make_image_document(path, lines, *, width=800, height=1000, font_size=20):
    """Create a document as a JPG image directly (for cases needing image format)."""
    img = Image.new("RGB", (width, height), color="white")
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size - 4)
    except (OSError, IOError):
        font = ImageFont.load_default()
        small_font = font

    y = 40
    for line in lines:
        if line.startswith("##"):
            draw.text((40, y), line[2:].strip(), fill="black", font=font)
            y += font_size + 12
        else:
            draw.text((40, y), line, fill="black", font=small_font)
            y += font_size + 4

    img.save(path, "JPEG", quality=90)


# --- Test Case Document Generation ---


def generate_tc001(case_dir):
    """Wrong Document Uploaded — two prescriptions, no hospital bill. Both as JPG (phone photos)."""
    make_image_document(os.path.join(case_dir, "dr_sharma_prescription.jpg"), [
        "## Dr. Arun Sharma, MBBS, MD (Internal Medicine)",
        "Reg. No: KA/45678/2015",
        "City Medical Centre, 12 MG Road, Bengaluru",
        "Ph: +91-80-XXXXXXXX",
        "",
        "Patient: Rajesh Kumar          Date: 01-Nov-2024",
        "Age: 39 years   Gender: M",
        "",
        "Diagnosis: Viral Fever",
        "",
        "Rx:",
        "1. Tab Paracetamol 650mg -- 1-1-1 x 5 days",
        "2. Tab Vitamin C 500mg -- 0-0-1 x 7 days",
        "",
        "Investigations: CBC, Dengue NS1",
        "Follow-up: After 5 days if no improvement",
        "",
        "                         [Doctor's Signature]",
        "                         [Registration Stamp]",
    ])
    make_image_document(os.path.join(case_dir, "another_prescription.jpg"), [
        "## Dr. Meera Iyer, MBBS, MD (Pulmonology)",
        "Reg. No: KA/55678/2017",
        "Bengaluru Chest Clinic, Jayanagar",
        "Ph: +91-80-XXXXXXXX",
        "",
        "Patient: Rajesh Kumar          Date: 01-Nov-2024",
        "Age: 39 years   Gender: M",
        "",
        "Diagnosis: Upper Respiratory Infection",
        "",
        "Rx:",
        "1. Tab Azithromycin 500mg -- 1-0-0 x 3 days",
        "",
        "                         [Doctor's Signature]",
    ])


def generate_tc002(case_dir):
    """Unreadable Document — good prescription, blurry pharmacy bill."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. Lakshmi Nair",
        doctor_reg="KA/67890/2016",
        patient_name="Sneha Reddy",
        date="2024-10-25",
        diagnosis="Acute Sinusitis",
        medicines=["Amoxicillin 500mg", "Cetirizine 10mg"],
    )
    # Generate a clear pharmacy bill first, then degrade it
    clear_path = os.path.join(case_dir, "_temp_clear_bill.jpg")
    make_image_document(clear_path, [
        "## HEALTH FIRST PHARMACY",
        "Drug Lic. No: KA-BLR-XXXX",
        "22 Brigade Road, Bengaluru",
        "",
        "Patient: Sneha Reddy",
        "Date: 2024-10-25",
        "Dr: Dr. Lakshmi Nair",
        "",
        "Amoxicillin 500mg    x10    Rs 45.00    Rs 450.00",
        "Cetirizine 10mg      x10    Rs 15.00    Rs 150.00",
        "",
        "Subtotal: Rs 600.00",
        "Discount: Rs 0.00",
        "Net Amount: Rs 600.00",
        "",
        "[Pharmacist Stamp]",
    ])
    apply_heavy_degradation(clear_path, os.path.join(case_dir, "blurry_bill.jpg"))
    os.remove(clear_path)


def generate_tc003(case_dir):
    """Documents Belong to Different Patients. Prescription as JPG, bill as JPG."""
    make_image_document(os.path.join(case_dir, "prescription_rajesh.jpg"), [
        "## Dr. Arun Sharma, MBBS, MD (Internal Medicine)",
        "Reg. No: KA/45678/2015",
        "City Medical Centre, 12 MG Road, Bengaluru",
        "",
        "Patient: Rajesh Kumar          Date: 01-Nov-2024",
        "Age: 39 years   Gender: M",
        "",
        "Diagnosis: Viral Fever",
        "",
        "Rx:",
        "1. Tab Paracetamol 650mg -- 1-1-1 x 5 days",
        "",
        "                         [Doctor's Signature]",
    ])
    make_image_document(os.path.join(case_dir, "bill_arjun.jpg"), [
        "## CITY MEDICAL CENTRE",
        "12 MG Road, Bengaluru - 560001",
        "GSTIN: 29XXXXX1234X1ZX",
        "",
        "BILL / RECEIPT",
        "Bill No: CMC/2024/08321    Date: 01-Nov-2024",
        "",
        "Patient Name: Arjun Mehta",
        "Age/Gender: 35 / Male",
        "",
        "DESCRIPTION                         AMOUNT",
        "Consultation Fee (OPD)              1000.00",
        "CBC (Complete Blood Count)           300.00",
        "Dengue NS1 Antigen Test              200.00",
        "",
        "Total Amount:                       1500.00",
        "",
        "Payment Mode: UPI",
        "[Cashier Stamp]",
    ])


def generate_tc004(case_dir):
    """Clean Consultation — Full Approval. Prescription as blurry phone-photo JPG, bill as blurry JPG."""
    clear_path = os.path.join(case_dir, "_temp_rx.jpg")
    make_image_document(clear_path, [
        "## Dr. Arun Sharma, MBBS, MD (Internal Medicine)",
        "Reg. No: KA/45678/2015",
        "City Clinic, Bengaluru",
        "Ph: +91-80-XXXXXXXX",
        "",
        "Patient: Rajesh Kumar          Date: 01-Nov-2024",
        "Age: 39 years   Gender: M",
        "",
        "Diagnosis: Viral Fever",
        "",
        "Rx:",
        "1. Tab Paracetamol 650mg -- 1-1-1 x 5 days",
        "2. Tab Vitamin C 500mg -- 0-0-1 x 7 days",
        "",
        "Investigations: CBC, Dengue NS1",
        "",
        "                         [Doctor's Signature]",
        "                         [Registration Stamp]",
    ])
    apply_moderate_degradation(clear_path, os.path.join(case_dir, "prescription.jpg"))
    os.remove(clear_path)

    clear_bill = os.path.join(case_dir, "_temp_bill.jpg")
    make_image_document(clear_bill, [
        "## CITY CLINIC, BENGALURU",
        "12 MG Road, Bengaluru - 560001",
        "GSTIN: 29XXXXX1234X1ZX",
        "",
        "BILL / RECEIPT",
        "Bill No: CC/2024/08321    Date: 01-Nov-2024",
        "",
        "Patient Name: Rajesh Kumar",
        "Age/Gender: 39 / Male",
        "Consulting Doctor: Dr. Arun Sharma",
        "",
        "DESCRIPTION                         AMOUNT (INR)",
        "Consultation Fee (OPD)              1000.00",
        "CBC (Complete Blood Count)           300.00",
        "Dengue NS1 Antigen Test              200.00",
        "",
        "Total Amount:                       1500.00",
        "",
        "Payment Mode: UPI",
        "[Cashier Stamp]",
    ])
    apply_moderate_degradation(clear_bill, os.path.join(case_dir, "hospital_bill.jpg"))
    os.remove(clear_bill)


def generate_tc005(case_dir):
    """Waiting Period — Diabetes."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. Sunil Mehta",
        doctor_reg="GJ/56789/2014",
        patient_name="Vikram Joshi",
        date="2024-10-15",
        diagnosis="Type 2 Diabetes Mellitus",
        medicines=["Metformin 500mg", "Glimepiride 1mg"],
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Gujarat Medical Centre",
        patient_name="Vikram Joshi",
        date="2024-10-15",
        line_items=[
            {"description": "Endocrinology Consultation", "amount": 2000},
            {"description": "HbA1c Test", "amount": 500},
            {"description": "Fasting Blood Sugar", "amount": 500},
        ],
        total=3000,
    )


def generate_tc006(case_dir):
    """Dental Partial Approval — Cosmetic Exclusion."""
    make_hospital_bill_pdf(
        os.path.join(case_dir, "dental_bill.pdf"),
        hospital_name="Smile Dental Clinic",
        patient_name="Priya Singh",
        date="2024-10-15",
        line_items=[
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000},
        ],
        total=12000,
    )


def generate_tc007(case_dir):
    """MRI Without Pre-Authorization."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. Venkat Rao",
        doctor_reg="AP/67890/2017",
        patient_name="Suresh Patil",
        date="2024-11-02",
        diagnosis="Suspected Lumbar Disc Herniation",
        tests_ordered=["MRI Lumbar Spine"],
    )
    make_lab_report_pdf(
        os.path.join(case_dir, "mri_report.pdf"),
        patient_name="Suresh Patil",
        doctor_name="Dr. Venkat Rao",
        date="2024-11-02",
        test_name="MRI Lumbar Spine",
        results=[
            {"param": "L4-L5 Disc", "result": "Mild bulge", "range": "N/A"},
            {"param": "L5-S1 Disc", "result": "Normal", "range": "N/A"},
            {"param": "Spinal Canal", "result": "No stenosis", "range": "N/A"},
        ],
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Aster CMI Hospital",
        patient_name="Suresh Patil",
        date="2024-11-02",
        line_items=[{"description": "MRI Lumbar Spine", "amount": 15000}],
        total=15000,
    )


def generate_tc008(case_dir):
    """Per-Claim Limit Exceeded."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. R. Gupta",
        doctor_reg="DL/34567/2016",
        patient_name="Amit Verma",
        date="2024-10-20",
        diagnosis="Gastroenteritis",
        medicines=["Antibiotics", "Probiotics", "ORS"],
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Delhi Medical Centre",
        patient_name="Amit Verma",
        date="2024-10-20",
        line_items=[
            {"description": "Consultation Fee", "amount": 2000},
            {"description": "Medicines", "amount": 5500},
        ],
        total=7500,
    )


def generate_tc009(case_dir):
    """Fraud Signal — Multiple Same-Day Claims. Prescription PDF, bill as phone-photo JPG."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. S. Khan",
        doctor_reg="KA/78901/2018",
        patient_name="Ravi Menon",
        date="2024-10-30",
        diagnosis="Migraine",
        medicines=["Sumatriptan 50mg", "Domperidone 10mg"],
    )
    clear_path = os.path.join(case_dir, "_temp_bill.jpg")
    make_image_document(clear_path, [
        "## WELLNESS CENTRE",
        "15 Indiranagar, Bengaluru - 560038",
        "",
        "BILL / RECEIPT",
        "Bill No: WC/2024/04512    Date: 30-Oct-2024",
        "",
        "Patient Name: Ravi Menon",
        "Referring Doctor: Dr. S. Khan",
        "",
        "DESCRIPTION                         AMOUNT",
        "Neurologist Consultation            2500.00",
        "Medicines                           2300.00",
        "",
        "Total Amount:                       4800.00",
        "",
        "Payment Mode: Card",
        "[Cashier Stamp]",
    ])
    apply_light_degradation(clear_path, os.path.join(case_dir, "hospital_bill.jpg"))
    os.remove(clear_path)


def generate_tc010(case_dir):
    """Network Hospital — Discount Applied. Blurry phone photos that still get approved."""
    clear_rx = os.path.join(case_dir, "_temp_rx.jpg")
    make_image_document(clear_rx, [
        "## Dr. S. Iyer, MBBS, MD (Pulmonology)",
        "Reg. No: TN/56789/2013",
        "Apollo Hospitals, Chennai",
        "Ph: +91-44-28290200",
        "",
        "Patient: Deepak Shah            Date: 03-Nov-2024",
        "Age: 44 years   Gender: M",
        "",
        "Diagnosis: Acute Bronchitis",
        "",
        "Rx:",
        "1. Cap Amoxicillin 500mg -- 1-0-1 x 7 days",
        "2. Salbutamol Inhaler -- 2 puffs SOS",
        "3. Tab Montelukast 10mg -- 0-0-1 x 14 days",
        "",
        "Follow-up: After 7 days",
        "",
        "                         [Doctor's Signature]",
        "                         [Registration Stamp]",
    ])
    apply_moderate_degradation(clear_rx, os.path.join(case_dir, "prescription.jpg"))
    os.remove(clear_rx)

    clear_bill = os.path.join(case_dir, "_temp_bill.jpg")
    make_image_document(clear_bill, [
        "## APOLLO HOSPITALS",
        "21 Greams Lane, Chennai - 600006",
        "GSTIN: 33AABCA1234H1ZX",
        "",
        "BILL / RECEIPT",
        "Bill No: APL/2024/56789    Date: 03-Nov-2024",
        "",
        "Patient Name: Deepak Shah",
        "Age/Gender: 44 / Male",
        "Consulting Doctor: Dr. S. Iyer",
        "",
        "DESCRIPTION                         AMOUNT (INR)",
        "Consultation Fee                    1500.00",
        "Medicines                           3000.00",
        "",
        "Total Amount:                       4500.00",
        "",
        "Payment Mode: Card",
        "[Cashier Stamp]           [Authorized Signatory]",
    ])
    apply_moderate_degradation(clear_bill, os.path.join(case_dir, "hospital_bill.jpg"))
    os.remove(clear_bill)


def generate_tc011(case_dir):
    """Component Failure — Graceful Degradation. Prescription as lightly degraded JPG, bill as PDF."""
    clear_path = os.path.join(case_dir, "_temp_rx.jpg")
    make_image_document(clear_path, [
        "## Vaidya T. Krishnan, BAMS",
        "Reg. No: AYUR/KL/2345/2019",
        "Ayur Wellness Centre, Kochi",
        "",
        "Patient: Kavita Nair            Date: 28-Oct-2024",
        "Age: 41 years   Gender: F",
        "",
        "Diagnosis: Chronic Joint Pain",
        "Treatment: Panchakarma Therapy",
        "",
        "Advised: 5 sessions of Panchakarma",
        "Duration: 2 weeks",
        "",
        "                         [Practitioner's Signature]",
        "                         [Registration Stamp]",
    ])
    apply_light_degradation(clear_path, os.path.join(case_dir, "prescription.jpg"))
    os.remove(clear_path)
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Ayur Wellness Centre",
        patient_name="Kavita Nair",
        date="2024-10-28",
        line_items=[
            {"description": "Panchakarma Therapy (5 sessions)", "amount": 3000},
            {"description": "Consultation", "amount": 1000},
        ],
        total=4000,
    )


def generate_tc012(case_dir):
    """Excluded Treatment — Obesity/Bariatric."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. P. Banerjee",
        doctor_reg="WB/34567/2015",
        patient_name="Anita Desai",
        date="2024-10-18",
        diagnosis="Morbid Obesity - BMI 37",
        treatment="Bariatric Consultation and Customised Diet Plan",
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Kolkata Wellness Hospital",
        patient_name="Anita Desai",
        date="2024-10-18",
        line_items=[
            {"description": "Bariatric Consultation", "amount": 3000},
            {"description": "Personalised Diet and Nutrition Program", "amount": 5000},
        ],
        total=8000,
    )


def generate_tc013(case_dir):
    """Vision Category — Glasses Claim. Prescription as JPG, bill as PDF."""
    make_image_document(os.path.join(case_dir, "prescription.jpg"), [
        "## Dr. Anil Kapoor, MS (Ophthalmology)",
        "Reg. No: MH/23456/2018",
        "VisionCare Eye Hospital, Mumbai",
        "",
        "Patient: Priya Singh            Date: 10-Oct-2024",
        "Age: 34 years   Gender: F",
        "",
        "Diagnosis: Myopia (Progressive)",
        "",
        "Refraction:",
        "  Right Eye: SPH -2.50, CYL -0.50, Axis 180",
        "  Left Eye:  SPH -2.75, CYL -0.50, Axis 175",
        "",
        "Advised: Corrective Lenses (Progressive)",
        "",
        "                         [Doctor's Signature]",
    ])
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="VisionCare Opticals",
        patient_name="Priya Singh",
        date="2024-10-10",
        line_items=[
            {"description": "Eye Examination", "amount": 500},
            {"description": "Prescription Glasses (Progressive)", "amount": 4000},
        ],
        total=4500,
    )


def generate_tc014(case_dir):
    """Vision — LASIK Exclusion. Both as PDF."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. Neha Jain",
        doctor_reg="KA/34567/2016",
        patient_name="Sneha Reddy",
        date="2024-11-05",
        diagnosis="High Myopia (-6.0D bilateral)",
        treatment="LASIK Surgery recommended",
        clinic_name="Clear Vision Eye Centre",
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Clear Vision Eye Centre",
        patient_name="Sneha Reddy",
        date="2024-11-05",
        line_items=[
            {"description": "LASIK Surgery (Both Eyes)", "amount": 45000},
        ],
        total=45000,
    )


def generate_tc015(case_dir):
    """Dependent Claim — Spouse. Both as blurry phone-photo JPGs that still get approved."""
    clear_rx = os.path.join(case_dir, "_temp_rx.jpg")
    make_image_document(clear_rx, [
        "## Dr. Kavitha Rao, MBBS, MD (Neurology)",
        "Reg. No: KA/89012/2019",
        "City Medical Centre, Bengaluru",
        "Ph: +91-80-XXXXXXXX",
        "",
        "Patient: Sunita Kumar           Date: 20-Oct-2024",
        "Age: 37 years   Gender: F",
        "",
        "Diagnosis: Acute Migraine",
        "",
        "Rx:",
        "1. Tab Sumatriptan 50mg -- SOS (max 2/day)",
        "2. Tab Ondansetron 4mg -- SOS for nausea",
        "",
        "Follow-up: 2 weeks if recurring",
        "",
        "                         [Doctor's Signature]",
        "                         [Registration Stamp]",
    ])
    apply_moderate_degradation(clear_rx, os.path.join(case_dir, "prescription.jpg"))
    os.remove(clear_rx)

    clear_bill = os.path.join(case_dir, "_temp_bill.jpg")
    make_image_document(clear_bill, [
        "## CITY MEDICAL CENTRE",
        "12 MG Road, Bengaluru - 560001",
        "GSTIN: 29XXXXX1234X1ZX",
        "",
        "BILL / RECEIPT",
        "Bill No: CMC/2024/10234    Date: 20-Oct-2024",
        "",
        "Patient Name: Sunita Kumar",
        "Age/Gender: 37 / Female",
        "Consulting Doctor: Dr. Kavitha Rao",
        "",
        "DESCRIPTION                         AMOUNT (INR)",
        "Neurology Consultation              1500.00",
        "Medicines (Sumatriptan, etc.)        1000.00",
        "",
        "Total Amount:                       2500.00",
        "",
        "Payment Mode: Cash",
        "[Cashier Stamp]",
    ])
    apply_moderate_degradation(clear_bill, os.path.join(case_dir, "hospital_bill.jpg"))
    os.remove(clear_bill)


def generate_tc016(case_dir):
    """Annual OPD Limit Exhausted. Both as PDF (network hospital)."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. M. Reddy",
        doctor_reg="AP/67890/2017",
        patient_name="Kavita Nair",
        date="2024-11-10",
        diagnosis="Seasonal Allergic Rhinitis",
        medicines=["Montelukast 10mg", "Levocetirizine 5mg"],
        clinic_name="Apollo Hospitals",
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Apollo Hospitals",
        patient_name="Kavita Nair",
        date="2024-11-10",
        line_items=[
            {"description": "Allergy Specialist Consultation", "amount": 2000},
            {"description": "Medicines", "amount": 2000},
        ],
        total=4000,
    )


def generate_tc017(case_dir):
    """Initial 30-Day Waiting Period. Prescription JPG, bill PDF."""
    make_image_document(os.path.join(case_dir, "prescription.jpg"), [
        "## Dr. A. Sharma, MBBS",
        "Reg. No: GJ/56789/2014",
        "Gujarat Medical Centre, Ahmedabad",
        "",
        "Patient: Vikram Joshi           Date: 20-Sep-2024",
        "Age: 45 years   Gender: M",
        "",
        "Diagnosis: Acute Gastritis",
        "",
        "Rx:",
        "1. Tab Pantoprazole 40mg -- 1-0-0 x 14 days",
        "2. Tab Domperidone 10mg -- 1-1-1 x 7 days",
        "",
        "                         [Doctor's Signature]",
    ])
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Gujarat Medical Centre",
        patient_name="Vikram Joshi",
        date="2024-09-20",
        line_items=[
            {"description": "Consultation Fee", "amount": 1000},
            {"description": "Medicines", "amount": 800},
        ],
        total=1800,
    )


def generate_tc018(case_dir):
    """Branded Drug Co-Pay (Pharmacy). Prescription PDF, pharmacy bill as JPG."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. R. Gupta",
        doctor_reg="DL/34567/2016",
        patient_name="Amit Verma",
        date="2024-10-28",
        diagnosis="Hypertension",
        medicines=["Telma-40 (Telmisartan 40mg)", "Ecosprin-75 (Aspirin 75mg)"],
    )
    make_image_document(os.path.join(case_dir, "pharmacy_bill.jpg"), [
        "## MEDPLUS PHARMACY",
        "Drug Lic. No: DL-DEL-4521",
        "45 Connaught Place, New Delhi",
        "",
        "Bill No: MP/2024/18923    Date: 28-Oct-2024",
        "Patient: Amit Verma",
        "Dr: Dr. R. Gupta",
        "",
        "MEDICINE                    QTY   MRP     AMT",
        "Telma-40 (Branded)          30    60.00   1800.00",
        "Ecosprin-75 (Branded)       30    20.00    600.00",
        "",
        "Subtotal:                               2400.00",
        "Net Amount:                             2400.00",
        "",
        "Note: Generic alternatives available",
        "[Pharmacist: R. Kumar]",
    ])


def generate_tc019(case_dir):
    """Submission Deadline Exceeded. Both PDF (network hospital)."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. Suresh Patil",
        doctor_reg="KA/45678/2015",
        patient_name="Suresh Patil",
        date="2024-08-15",
        diagnosis="Lower Back Pain",
        medicines=["Diclofenac 50mg", "Thiocolchicoside 4mg"],
        clinic_name="Manipal Hospitals",
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Manipal Hospitals",
        patient_name="Suresh Patil",
        date="2024-08-15",
        line_items=[
            {"description": "Orthopaedic Consultation", "amount": 2000},
            {"description": "X-Ray Lumbar Spine", "amount": 1000},
        ],
        total=3000,
    )


def generate_tc020(case_dir):
    """Below Minimum Claim Amount. Prescription PDF, pharmacy bill as lightly degraded JPG."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. Lakshmi Nair",
        doctor_reg="KA/67890/2016",
        patient_name="Sneha Reddy",
        date="2024-10-30",
        diagnosis="Common Cold",
        medicines=["Cetirizine 10mg", "Paracetamol 500mg"],
    )
    clear_path = os.path.join(case_dir, "_temp_bill.jpg")
    make_image_document(clear_path, [
        "## HEALTH FIRST PHARMACY",
        "Drug Lic. No: KA-BLR-XXXX",
        "22 Brigade Road, Bengaluru",
        "",
        "Bill No: HFP-24-11205    Date: 30-Oct-2024",
        "Patient: Sneha Reddy",
        "Dr: Dr. Lakshmi Nair",
        "",
        "MEDICINE                    QTY   MRP     AMT",
        "Cetirizine 10mg             10    15.00   150.00",
        "Paracetamol 500mg           10    20.00   200.00",
        "",
        "Subtotal:                                350.00",
        "Net Amount:                              350.00",
        "",
        "[Pharmacist Stamp]",
    ])
    apply_light_degradation(clear_path, os.path.join(case_dir, "pharmacy_bill.jpg"))
    os.remove(clear_path)


def generate_tc021(case_dir):
    """Monthly Claims Limit Exceeded. Both as PDF."""
    make_prescription_pdf(
        os.path.join(case_dir, "prescription.pdf"),
        doctor_name="Dr. V. Menon",
        doctor_reg="KL/78901/2012",
        patient_name="Ravi Menon",
        date="2024-10-29",
        diagnosis="Tension Headache",
        medicines=["Ibuprofen 400mg"],
    )
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Kerala Medical Centre",
        patient_name="Ravi Menon",
        date="2024-10-29",
        line_items=[
            {"description": "GP Consultation", "amount": 1000},
            {"description": "Medicines", "amount": 1000},
        ],
        total=2000,
    )


def generate_tc022(case_dir):
    """Sub-Limit Exceeded — Consultation. Prescription as JPG, bill as PDF (network hospital)."""
    clear_path = os.path.join(case_dir, "_temp_rx.jpg")
    make_image_document(clear_path, [
        "## Dr. K. Murthy, MS (Orthopaedics)",
        "Reg. No: TN/56789/2013",
        "Fortis Healthcare, Chennai",
        "",
        "Patient: Deepak Shah            Date: 08-Nov-2024",
        "Age: 44 years   Gender: M",
        "",
        "Diagnosis: Cervical Spondylitis",
        "",
        "Rx:",
        "1. Cap Pregabalin 75mg -- 0-0-1 x 14 days",
        "2. Tab Methylcobalamin 1500mcg -- 1-0-1 x 30 days",
        "",
        "Investigations: X-Ray Cervical Spine (AP + Lateral)",
        "",
        "                         [Doctor's Signature]",
    ])
    apply_light_degradation(clear_path, os.path.join(case_dir, "prescription.jpg"))
    os.remove(clear_path)
    make_hospital_bill_pdf(
        os.path.join(case_dir, "hospital_bill.pdf"),
        hospital_name="Fortis Healthcare",
        patient_name="Deepak Shah",
        date="2024-11-08",
        line_items=[
            {"description": "Specialist Consultation", "amount": 2500},
            {"description": "X-Ray Cervical Spine", "amount": 1000},
            {"description": "Medicines", "amount": 1000},
        ],
        total=4500,
    )


# --- Main ---


def main():
    ensure_dir(OUTPUT_DIR)

    generators = [
        ("TC001", generate_tc001),
        ("TC002", generate_tc002),
        ("TC003", generate_tc003),
        ("TC004", generate_tc004),
        ("TC005", generate_tc005),
        ("TC006", generate_tc006),
        ("TC007", generate_tc007),
        ("TC008", generate_tc008),
        ("TC009", generate_tc009),
        ("TC010", generate_tc010),
        ("TC011", generate_tc011),
        ("TC012", generate_tc012),
        ("TC013", generate_tc013),
        ("TC014", generate_tc014),
        ("TC015", generate_tc015),
        ("TC016", generate_tc016),
        ("TC017", generate_tc017),
        ("TC018", generate_tc018),
        ("TC019", generate_tc019),
        ("TC020", generate_tc020),
        ("TC021", generate_tc021),
        ("TC022", generate_tc022),
    ]

    for case_id, gen_fn in generators:
        case_dir = os.path.join(OUTPUT_DIR, case_id)
        ensure_dir(case_dir)
        gen_fn(case_dir)
        print(f"  {case_id}: generated in {case_dir}/")

    # Generate a manifest mapping file_ids to paths
    manifest = {}
    for case_id, _ in generators:
        case_dir = os.path.join(OUTPUT_DIR, case_id)
        files = sorted(os.listdir(case_dir))
        manifest[case_id] = files

    manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n  Manifest written to {manifest_path}")
    print(f"\nDone. All test documents in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
