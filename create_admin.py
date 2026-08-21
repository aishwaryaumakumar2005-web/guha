import os
from app import create_app
from app.models import User
from werkzeug.security import generate_password_hash

def create_admin_user():
    """Create a default admin user if it doesn't exist"""
    app = create_app()
    
    with app.app_context():
        # Check if admin user already exists
        admin = User.query.filter_by(username='admin').first()
        
        if admin:
            print("Admin user already exists!")
            print(f"Username: admin")
            print("To reset password, delete the user and run this script again.")
            return
        
        # Create default admin user
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            name='Administrator',
            email='admin@guhaindia.in'
        )
        
        db.session.add(admin)
        db.session.commit()
        
        print("Admin user created successfully!")
        print("Username: admin")
        print("Password: admin123")
        print("Please change this password after first login!")

if __name__ == '__main__':
    from app.extensions import db
    create_admin_user()