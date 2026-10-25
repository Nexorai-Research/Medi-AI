"""Patients CRUD routes."""
import re
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.models.patient import Patient
from app.models.sequence import Sequence
from app.models.sales import Sale
from app.models.prescription import Prescription


@bp.route('/')
@login_required
def index():
    bid = current_user.business_id
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    query = Patient.query.filter_by(business_id=bid)
    if q:
        query = query.filter(db.or_(Patient.full_name.ilike(f'%{q}%'), Patient.phone.ilike(f'%{q}%'), Patient.patient_code.ilike(f'%{q}%')))
    patients = query.order_by(Patient.full_name).paginate(page=page, per_page=25)
    return render_template('patients/index.html', title='Patients', patients=patients, q=q)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    bid = current_user.business_id
    if request.method == 'POST':
        code, _ = Sequence.next_number(f'patient-{bid}', prefix='PAT-', pad=5)
        p = Patient(
            business_id=bid, patient_code=code, full_name=request.form.get('full_name', '').strip(),
            phone=request.form.get('phone', '').strip(), email=request.form.get('email', '').strip() or None,
            gender=request.form.get('gender') or None, address=request.form.get('address', '').strip() or None,
            blood_group=request.form.get('blood_group') or None, abha_id=request.form.get('abha_id', '').strip() or None,
            allergies=request.form.get('allergies', '').strip() or None,
            chronic_conditions=request.form.get('chronic_conditions', '').strip() or None,
            is_active=True,
        )
        error = None
        dob = request.form.get('dob')
        if dob:
            try:
                p.dob = datetime.strptime(dob, '%Y-%m-%d').date()
            except ValueError:
                error = 'Invalid date of birth.'
        if not p.full_name:
            error = 'Patient name is required.'
        elif p.phone and not re.fullmatch(r'\+?\d{10,13}', p.phone):
            error = 'Enter a valid phone number (10-13 digits).'
        elif p.phone and Patient.query.filter_by(business_id=bid, phone=p.phone, is_active=True).first():
            error = 'A patient with this phone number already exists.'
        if error:
            flash(error, 'danger')
            return render_template('patients/form.html', title='Add Patient', patient=None)
        db.session.add(p)
        db.session.commit()
        flash(f'Patient {p.patient_code} added.', 'success')
        return redirect(url_for('patients.detail', patient_id=p.id))
    return render_template('patients/form.html', title='Add Patient', patient=None)


@bp.route('/<int:patient_id>')
@login_required
def detail(patient_id):
    patient = Patient.query.filter_by(id=patient_id, business_id=current_user.business_id).first_or_404()
    sales = Sale.query.filter_by(patient_id=patient.id).order_by(Sale.invoice_date.desc()).limit(20).all()
    prescriptions = Prescription.query.filter_by(patient_id=patient.id).order_by(Prescription.rx_date.desc()).limit(20).all()
    return render_template('patients/detail.html', title=patient.full_name, patient=patient, sales=sales, prescriptions=prescriptions)


@bp.route('/<int:patient_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(patient_id):
    patient = Patient.query.filter_by(id=patient_id, business_id=current_user.business_id).first_or_404()
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        dob = request.form.get('dob')
        error = None
        if not request.form.get('full_name', '').strip():
            error = 'Patient name is required.'
        elif phone and not re.fullmatch(r'\+?\d{10,13}', phone):
            error = 'Enter a valid phone number (10-13 digits).'
        elif phone and Patient.query.filter(Patient.business_id == current_user.business_id, Patient.phone == phone,
                                             Patient.is_active.is_(True), Patient.id != patient.id).first():
            error = 'Another patient already uses this phone number.'
        if dob:
            try:
                datetime.strptime(dob, '%Y-%m-%d')
            except ValueError:
                error = 'Invalid date of birth.'
        if error:
            flash(error, 'danger')
            return render_template('patients/form.html', title='Edit Patient', patient=patient)
        patient.full_name = request.form.get('full_name', '').strip()
        patient.phone = phone
        patient.email = request.form.get('email', '').strip() or None
        patient.gender = request.form.get('gender') or None
        patient.address = request.form.get('address', '').strip() or None
        patient.blood_group = request.form.get('blood_group') or None
        patient.abha_id = request.form.get('abha_id', '').strip() or None
        patient.allergies = request.form.get('allergies', '').strip() or None
        patient.chronic_conditions = request.form.get('chronic_conditions', '').strip() or None
        patient.is_active = 'is_active' in request.form
        if dob:
            patient.dob = datetime.strptime(dob, '%Y-%m-%d').date()
        db.session.commit()
        flash('Patient updated.', 'success')
        return redirect(url_for('patients.detail', patient_id=patient.id))
    return render_template('patients/form.html', title='Edit Patient', patient=patient)


@bp.route('/<int:patient_id>/delete', methods=['POST'])
@login_required
def delete(patient_id):
    patient = Patient.query.filter_by(id=patient_id, business_id=current_user.business_id).first_or_404()
    patient.is_active = False
    db.session.commit()
    flash('Patient deactivated.', 'info')
    return redirect(url_for('patients.index'))
