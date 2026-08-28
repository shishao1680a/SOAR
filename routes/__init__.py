# routes package
from .main_routes import main_bp
from .auth_routes import auth_bp
from .product_routes import product_bp
from .bulletin_routes import bulletin_bp
from .admin_routes import admin_bp
from .material_routes import material_bp
from .order_routes import order_bp
from .line_routes import line_bp

__all__ = [
    'main_bp',
    'auth_bp',
    'product_bp',
    'bulletin_bp',
    'admin_bp',
    'material_bp',
    'order_bp',
    'line_bp',
]
