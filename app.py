from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, login_required, current_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import select, delete, or_
from flask_migrate import Migrate
from models import db, User, BirdCategory, UserBirds, Award
from datetime import datetime
from sqlalchemy import func, select


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///aves.db'
app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads/profile_images'

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


def create_default_data():
    with app.app_context():
        # Crear admin si no existe
        if not db.session.execute(select(User).filter_by(username='admin')).scalar():
            admin = User(
                username='admin',
                email='admin@aves.com',
                role='admin',
                full_name='Administrador Principal',
                phone='0000000000',
                is_associated=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✔ Admin creado: usuario='admin' / contraseña='admin123'")

        # Crear categorías de aves si no existen
        if not db.session.execute(select(BirdCategory)).scalar():
            categories = [
                {'name': 'Canario de color', 'parent': None},
                {'name': 'Canario de canto', 'parent': None},
                {'name': 'Aves exóticas', 'parent': None},
                {'name': 'Psitácidas', 'parent': None},
                {'name': 'Paloma de raza', 'parent': None},
                {'name': 'Paloma de fantasía', 'parent': 'Paloma de raza'},
                {'name': 'Paloma deportiva', 'parent': 'Paloma de raza'},
                {'name': 'Gallináceas', 'parent': None}
            ]
            for cat in categories:
                db.session.add(BirdCategory(
                    name=cat['name'],
                    parent_category=cat['parent'],
                    resource_needs='Requerimientos básicos'
                ))
            db.session.commit()

with app.app_context():
    db.create_all()
    create_default_data()

# ----------- Autenticación -----------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.session.execute(
            select(User).filter_by(username=request.form['username'])
        ).scalar()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if db.session.execute(select(User).filter(or_(
            User.username == request.form['username'],
            User.email == request.form['email']
        ))).scalar():
            flash('Usuario o email ya registrado', 'danger')
            return redirect(url_for('register'))

        user = User(
            username=request.form['username'],
            email=request.form['email'],
            full_name=request.form['full_name'],
            phone=request.form['phone'],
            role='user',
            is_associated=False
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.commit()
        flash('Registro exitoso. Inicia sesión', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----------- Dashboard -----------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_users'))
    elif current_user.role in ['specialist', 'dependiente']:  
        return redirect(url_for('specialist_users'))
    return redirect(url_for('profile'))

# ----------- Admin Routes -----------
@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        abort(403)
    
    # Obtener parámetros de filtrado
    search_name = request.args.get('name', '').strip()
    award_year = request.args.get('award_year', '').strip()
    award_position = request.args.get('award_position', '').strip()  
    
    # Consulta base
    query = select(User).order_by(User.id)
    
    # Aplicar filtros
    if search_name:
        query = query.where(User.full_name.ilike(f'%{search_name}%'))
    
    if award_year:
        try:
            year = int(award_year)
            start_date = datetime(year, 1, 1)
            end_date = datetime(year + 1, 1, 1)
            
            # Subconsulta para usuarios con premios en ese año
            subquery = select(Award.user_id).where(
                Award.award_date >= start_date,
                Award.award_date < end_date
            ).distinct()
            
            query = query.where(User.id.in_(subquery))
        except ValueError:
            flash('Año de premio no válido', 'warning')
    
    # Nuevo filtro por posición en premios
    if award_position:
        # Subconsulta para usuarios con premios en esa posición
        position_subquery = select(Award.user_id).where(
            Award.position == award_position
        ).distinct()
        
        query = query.where(User.id.in_(position_subquery))
    
    users = db.session.execute(query).scalars()
    
    # Pasar el año actual al template
    current_year = datetime.now().year
    
    return render_template('admin/users.html', 
                         users=users, 
                         search_name=search_name, 
                         award_year=award_year,
                         award_position=award_position,  
                         current_year=current_year)
    
@app.route('/admin/assign_role/<int:user_id>', methods=['POST'])
@login_required
def assign_role(user_id):
    if current_user.role != 'admin':
        abort(403)
    
    user = db.session.get(User, user_id)
    if not user:
        flash('Usuario no encontrado', 'danger')
        return redirect(url_for('admin_users'))
    
    try:
        user.role = request.form['role']
        user.is_associated = request.form.get('is_associated') == 'true'
        db.session.commit()
        flash('Configuración de usuario actualizada', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar: {str(e)}', 'danger')
    
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    
    user = db.session.get(User, user_id)
    if not user:
        flash('Usuario no encontrado', 'danger')
    else:
        try:
            # Eliminar registros relacionados primero
            db.session.execute(delete(UserBirds).where(UserBirds.user_id == user_id))
            db.session.execute(delete(Award).where(Award.user_id == user_id))
            db.session.delete(user)
            db.session.commit()
            flash('Usuario eliminado correctamente', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al eliminar usuario: {str(e)}', 'danger')
    
    return redirect(url_for('admin_users'))

# ----------- Specialist/Dependiente Routes -----------
@app.route('/specialist/users')
@login_required
def specialist_users():
    if current_user.role not in ['specialist', 'dependiente']:
        abort(403)
    
    # Obtener usuarios asociados
    associated_users = db.session.execute(
        select(User).where(User.is_associated == True).order_by(User.full_name)
    ).scalars()
    
    # Preparar datos para la vista
    users_data = []
    for user in associated_users:  # Cambiado de 'user' a 'associated_users' para evitar conflicto
        # Obtener última actualización y cambios
        last_updated = None
        last_quantity_change = 0
        last_food_change = 0.0
        
        if user.birds:
            # Encontrar la última actualización
            last_updated = max(
                (bird.last_updated for bird in user.birds if bird.last_updated),
                default=None
            )
            
            # Calcular cambios
            quantities = [bird.quantity for bird in user.birds]
            if len(quantities) > 1:
                last_quantity_change = quantities[-1] - quantities[-2]
            
            foods = [bird.food_required for bird in user.birds if bird.food_required]
            if len(foods) > 1:
                last_food_change = foods[-1] - foods[-2]
        
        users_data.append({
            'user': user,
            'total_birds': sum(bird.quantity for bird in user.birds),
            'total_food': sum(bird.food_required for bird in user.birds if bird.food_required),
            'last_updated': last_updated,
            'last_quantity_change': last_quantity_change,
            'last_food_change': last_food_change
        })
    
    # Ordenar por usuarios con cambios recientes primero
    users_data.sort(key=lambda x: x['last_updated'] or datetime.min, reverse=True)
    
    return render_template('specialist/users.html', 
                         users=users_data,
                         current_role=current_user.role)
    
@app.route('/specialist/user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def manage_user(user_id):
    # Permitir acceso a especialistas y dependientes
    if current_user.role not in ['specialist', 'dependiente']:
        abort(403)
    
    user = db.session.get(User, user_id)
    if not user or not user.is_associated:
        flash('Usuario no asociado o no encontrado', 'danger')
        return redirect(url_for('specialist_users'))
    
    # Determinar si está en modo solo lectura (para dependientes)
    read_only = current_user.role == 'dependiente'
    
    if request.method == 'POST' and not read_only:  # Solo especialistas pueden hacer POST
        # Procesar actualizaciones de comida y nuevos campos
        for bird in user.birds:
            # Actualizar cantidad de comida
            food_key = f'food_{bird.id}'
            if food_key in request.form:
                try:
                    bird.food_per_bird = float(request.form[food_key]) if request.form[food_key] else None
                    bird.last_updated = datetime.utcnow()
                except ValueError:
                    flash(f'Valor inválido para {bird.category.name}', 'danger')
            
            # Actualizar tipo de alimento
            food_type_key = f'food_type_{bird.id}'
            if food_type_key in request.form:
                bird.food_type = request.form[food_type_key]
            
            # Actualizar proceso de alimento (solo si no es Arroz en cáscara)
            food_process_key = f'food_process_{bird.id}'
            if food_process_key in request.form and request.form.get(f'food_type_{bird.id}') != 'Arroz en cáscara':
                bird.food_process = request.form[food_process_key]
            elif request.form.get(f'food_type_{bird.id}') == 'Arroz en cáscara':
                bird.food_process = None
        
        # Procesar nuevo premio (solo si se proporciona el nombre del concurso)
        contest_name = request.form.get('contest_name')
        if contest_name:  # Solo procesar premios si hay un nombre de concurso
            award_date = request.form.get('award_date')
            position = request.form.get('position')  # Capturamos el puesto seleccionado
            
            try:
                award_date_obj = datetime.strptime(award_date, '%Y-%m-%d') if award_date else datetime.utcnow()
                
                if not position:  # Validar que se haya seleccionado un puesto
                    flash('Debe seleccionar un puesto para el premio', 'danger')
                else:
                    award = Award(
                        user_id=user_id,
                        contest_name=contest_name,
                        award_date=award_date_obj,
                        position=position,  
                        category=request.form.get('award_category', '')
                    )
                    db.session.add(award)
                    flash('Premio añadido correctamente', 'success')
            except ValueError as e:
                flash(f'Error al añadir premio: {str(e)}', 'danger')
        
        try:
            db.session.commit()
            flash('Datos actualizados correctamente', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar los datos: {str(e)}', 'danger')
        
        return redirect(url_for('manage_user', user_id=user_id))
    
    return render_template('specialist/manage_user.html', 
                         user=user,
                         current_role=current_user.role,
                         read_only=read_only,
                         categories=db.session.execute(select(BirdCategory)).scalars())
    
# ----------- User Routes -----------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    categories = db.session.execute(select(BirdCategory)).scalars()
    
    if request.method == 'POST':
        # Actualizar datos personales
        current_user.full_name = request.form['full_name']
        current_user.phone = request.form['phone']
        current_user.address = request.form['address']  
        
        # Actualizar cantidades de aves y exportación
        for category in categories:
            quantity = int(request.form.get(f'category_{category.id}', 0))
            export_quantity = int(request.form.get(f'export_{category.id}', 0))
            
            existing = next(
                (b for b in current_user.birds if b.category_id == category.id), 
                None
            )
            
            if existing:
                if quantity > 0:
                    existing.quantity = quantity
                    existing.export_quantity = min(export_quantity, quantity)  # Asegurar que no exceda
                else:
                    db.session.delete(existing)  # Eliminar si cantidad es 0
            elif quantity > 0:
                db.session.add(UserBirds(
                    user_id=current_user.id,
                    category_id=category.id,
                    quantity=quantity,
                    export_quantity=export_quantity
                ))
        
        db.session.commit()
        flash('Perfil actualizado correctamente', 'success')
        return redirect(url_for('profile'))
    
    return render_template('user/profile.html', categories=categories)

@app.route('/user/awards')
@login_required
def user_awards():
    if current_user.role != 'user':
        abort(403)
    return render_template('user/awards.html',
        awards=db.session.execute(select(Award).filter_by(user_id=current_user.id)).scalars()
    )
    
@app.route('/admin/user_details/<int:user_id>')
@login_required
def user_details(user_id):
    if current_user.role != 'admin':
        abort(403)
    
    user = db.session.get(User, user_id)
    if not user:
        flash('Usuario no encontrado', 'danger')
        return redirect(url_for('admin_users'))
    
    return render_template('admin/user_details.html', user=user)

@app.route('/admin/associates_report')
@login_required
def associates_report_view():
    if current_user.role != 'admin':
        abort(403)

    # Obtener todos los usuarios asociados
    associates = db.session.execute(
        select(User).where(User.is_associated == True).order_by(User.full_name)
    ).scalars()

    # Calcular totales por categoría para todos los asociados
    categories = db.session.execute(
        select(BirdCategory.name, 
               func.sum(UserBirds.quantity).label('total_quantity'),
               func.sum(UserBirds.export_quantity).label('total_export'))
        .select_from(UserBirds)
        .join(BirdCategory)
        .join(User)
        .where(User.is_associated == True)
        .group_by(BirdCategory.name)
    ).all()

    # Calcular totales generales
    grand_total = sum(cat.total_quantity or 0 for cat in categories)
    grand_export = sum(cat.total_export or 0 for cat in categories)

    return render_template('admin/associates_report.html',
                         associates=associates,
                         categories=categories,
                         grand_total=grand_total,
                         grand_export=grand_export,
                         now=datetime.utcnow())  
    
@app.route('/specialist/associates_report')
@login_required
def specialist_associates_report():
    if current_user.role != 'specialist':
        abort(403)
    
    # Reutilizamos la misma lógica que para admin
    associates = db.session.execute(
        select(User).where(User.is_associated == True).order_by(User.full_name)
    ).scalars()

    categories = db.session.execute(
        select(BirdCategory.name, 
               func.sum(UserBirds.quantity).label('total_quantity'),
               func.sum(UserBirds.export_quantity).label('total_export'))
        .select_from(UserBirds)
        .join(BirdCategory)
        .join(User)
        .where(User.is_associated == True)
        .group_by(BirdCategory.name)
    ).all()

    grand_total = sum(cat.total_quantity or 0 for cat in categories)
    grand_export = sum(cat.total_export or 0 for cat in categories)

    return render_template('admin/associates_report.html',
                         associates=associates,
                         categories=categories,
                         grand_total=grand_total,
                         grand_export=grand_export,
                         now=datetime.utcnow(),
                         current_role=current_user.role)  # Añadimos el rol actual
    
@app.route('/delete_award/<int:award_id>', methods=['POST'])
@login_required
def delete_award(award_id):
    if current_user.role not in ['admin', 'specialist']:
        abort(403)
    
    award = db.session.get(Award, award_id)
    if not award:
        flash('Premio no encontrado', 'danger')
        return redirect(url_for('specialist_users'))
    
    try:
        db.session.delete(award)
        db.session.commit()
        flash('Premio eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar premio: {str(e)}', 'danger')
    
    return redirect(url_for('manage_user', user_id=award.user_id))

# ----------- Report Routes -----------
@app.route('/reports/contact')
@login_required
def contact_report():
    if current_user.role not in ['admin', 'specialist']:
        abort(403)
    
    associates = db.session.execute(
        select(User).where(User.is_associated == True).order_by(User.full_name)
    ).scalars()
    
    return render_template('reports/contact_report.html',
                         associates=associates,
                         now=datetime.utcnow())

@app.route('/reports/birds')
@login_required
def birds_report():
    if current_user.role not in ['admin', 'specialist']:
        abort(403)
    
    associates = db.session.execute(
        select(User).where(User.is_associated == True)
        .order_by(User.full_name)
        .options(db.joinedload(User.birds).joinedload(UserBirds.category))
    ).scalars()
    
    return render_template('reports/birds_report.html',
                         associates=associates,
                         now=datetime.utcnow())

@app.route('/reports/awards')
@login_required
def awards_report():
    if current_user.role not in ['admin', 'specialist']:
        abort(403)
    
    # Solución 1: Usar subqueryload en lugar de joinedload para colecciones
    associates = db.session.execute(
        select(User)
        .where(User.is_associated == True)
        .order_by(User.full_name)
        .options(db.subqueryload(User.awards))  # Cambiado a subqueryload
    ).scalars().unique().all()  # Añadido unique() y all()
    
    # Solución alternativa 2: Si prefieres mantener joinedload
    # associates = db.session.execute(
    #     select(User)
    #     .where(User.is_associated == True)
    #     .order_by(User.full_name)
    #     .options(db.joinedload(User.awards))
    # ).unique().scalars().all()
    
    return render_template('reports/awards_report.html',
                         associates=associates,
                         now=datetime.utcnow())
if __name__ == '__main__':
    app.run(debug=True, port=5001)