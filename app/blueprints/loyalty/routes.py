"""Customer loyalty program routes."""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.models.loyalty import LoyaltyProgram, LoyaltyTransaction
from app.models.patient import Patient


def _get_program(bid):
    program = LoyaltyProgram.query.filter_by(business_id=bid).first()
    if not program:
        program = LoyaltyProgram(business_id=bid)
        db.session.add(program)
        db.session.commit()
    return program


@bp.route('/')
@login_required
def index():
    bid = current_user.business_id
    program = _get_program(bid)
    top_patients = (
        Patient.query.filter_by(business_id=bid).order_by(Patient.loyalty_points.desc()).limit(20).all()
    )
    return render_template('loyalty/index.html', title='Customer Loyalty', program=program, top_patients=top_patients)


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    bid = current_user.business_id
    program = _get_program(bid)
    if request.method == 'POST':
        program.points_per_rupee = float(request.form.get('points_per_rupee') or 1)
        program.rupees_per_point = float(request.form.get('rupees_per_point') or 0.25)
        program.min_redeem_points = int(request.form.get('min_redeem_points') or 100)
        program.silver_min_spend = float(request.form.get('silver_min_spend') or 0)
        program.gold_min_spend = float(request.form.get('gold_min_spend') or 10000)
        program.platinum_min_spend = float(request.form.get('platinum_min_spend') or 50000)
        program.silver_cashback_pct = float(request.form.get('silver_cashback_pct') or 0)
        program.gold_cashback_pct = float(request.form.get('gold_cashback_pct') or 2)
        program.platinum_cashback_pct = float(request.form.get('platinum_cashback_pct') or 5)
        program.referral_bonus_points = int(request.form.get('referral_bonus_points') or 50)
        db.session.commit()
        flash('Loyalty program settings updated.', 'success')
        return redirect(url_for('loyalty.settings'))
    return render_template('loyalty/settings.html', title='Loyalty Settings', program=program)


@bp.route('/patient/<int:patient_id>')
@login_required
def patient_history(patient_id):
    patient = Patient.query.filter_by(id=patient_id, business_id=current_user.business_id).first_or_404()
    txns = LoyaltyTransaction.query.filter_by(patient_id=patient.id).order_by(LoyaltyTransaction.created_at.desc()).all()
    return render_template('loyalty/patient_history.html', title='Loyalty History', patient=patient, txns=txns)


@bp.route('/redeem/<int:patient_id>', methods=['POST'])
@login_required
def redeem(patient_id):
    patient = Patient.query.filter_by(id=patient_id, business_id=current_user.business_id).first_or_404()
    program = _get_program(current_user.business_id)
    points = request.form.get('points', type=int) or 0
    if points < program.min_redeem_points:
        flash(f'Minimum {program.min_redeem_points} points required to redeem.', 'danger')
        return redirect(url_for('loyalty.patient_history', patient_id=patient.id))
    if points > (patient.loyalty_points or 0):
        flash('Insufficient points balance.', 'danger')
        return redirect(url_for('loyalty.patient_history', patient_id=patient.id))
    patient.loyalty_points -= points
    db.session.add(LoyaltyTransaction(
        patient_id=patient.id, type='redeem', points=-points, balance=patient.loyalty_points,
        notes=f'Redeemed {points} points (₹{float(points) * float(program.rupees_per_point):.2f} value)',
    ))
    db.session.commit()
    flash(f'{points} points redeemed.', 'success')
    return redirect(url_for('loyalty.patient_history', patient_id=patient.id))


@bp.route('/referral', methods=['POST'])
@login_required
def referral():
    bid = current_user.business_id
    program = _get_program(bid)
    referrer_id = request.form.get('referrer_patient_id')
    new_patient_id = request.form.get('new_patient_id')
    referrer = Patient.query.filter_by(id=referrer_id, business_id=bid).first()
    new_patient = Patient.query.filter_by(id=new_patient_id, business_id=bid).first()
    if not referrer or not new_patient:
        flash('Both referrer and new patient must be valid.', 'danger')
        return redirect(url_for('loyalty.index'))
    new_patient.referred_by_patient_id = referrer.id
    referrer.loyalty_points = (referrer.loyalty_points or 0) + program.referral_bonus_points
    db.session.add(LoyaltyTransaction(
        patient_id=referrer.id, type='referral', points=program.referral_bonus_points,
        balance=referrer.loyalty_points, notes=f'Referral bonus for referring {new_patient.full_name}',
    ))
    db.session.commit()
    flash(f'{program.referral_bonus_points} referral bonus points awarded to {referrer.full_name}.', 'success')
    return redirect(url_for('loyalty.index'))
