import os
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'ETL_db'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'Mouni@123')
}

# Create a connection pool
connection_pool = None

def init_db_pool(min_conn=1, max_conn=10):
    """Initialize the database connection pool"""
    global connection_pool
    try:
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            min_conn,
            max_conn,
            **DB_CONFIG
        )
        print("Database connection pool created successfully")
        
        # Create tables if they don't exist
        create_tables()
        
        return True
    except Exception as e:
        print(f"Error creating connection pool: {e}")
        return False

def get_connection():
    """Get a connection from the pool"""
    if connection_pool:
        return connection_pool.getconn()
    else:
        raise Exception("Connection pool not initialized")

def release_connection(conn):
    """Release a connection back to the pool"""
    if connection_pool:
        connection_pool.putconn(conn)

def create_tables():
    """Create database tables if they don't exist"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create workflows table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Create workflow_logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_logs (
            id SERIAL PRIMARY KEY,
            workflow_id INTEGER REFERENCES workflows(id),
            log_type VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        
        
        # Create transformation_rules table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transformation_rules (
            id SERIAL PRIMARY KEY,
            workflow_id INTEGER REFERENCES workflows(id),
            user_query TEXT,
            rules TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        conn.commit()
        print("Database tables created successfully")
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error creating tables: {e}")
    finally:
        if conn:
            release_connection(conn)

def get_workflows():
    """Get all workflows from the database"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM workflows")
        workflows = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
        return workflows
    except Exception as e:
        print(f"Error getting workflows: {e}")
        return []
    finally:
        if conn:
            release_connection(conn)

def get_workflow_data(workflow_id):
    """Get workflow data including source, target, and logs"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        
        
        # Get logs
        cursor.execute("SELECT log_type, message FROM workflow_logs WHERE workflow_id = %s", (workflow_id,))
        logs = [f"{row[0]}: {row[1]}" for row in cursor.fetchall()]
        
        return {
            
            "logs": logs
        }
    except Exception as e:
        print(f"Error getting workflow data: {e}")
        return {"source_data": "", "target_data": "", "logs": []}
    finally:
        if conn:
            release_connection(conn)

def save_transformation_rules(workflow_id, user_query, rules):
    """Save generated transformation rules to the database"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transformation_rules (workflow_id, user_query, rules) VALUES (%s, %s, %s) RETURNING id",
            (workflow_id, user_query, rules)
        )
        rule_id = cursor.fetchone()[0]
        conn.commit()
        return rule_id
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error saving transformation rules: {e}")
        return None
    finally:
        if conn:
            release_connection(conn)

def insert_sample_data():
    """Insert sample data into the database for testing"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check if we already have workflows
        cursor.execute("SELECT COUNT(*) FROM workflows")
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Insert sample workflows
            workflows = [
                ("Customer Data Migration", "Migration of customer data from legacy system to new platform"),
                ("Product Catalog Transformation", "Transformation of product catalog data to new format"),
                ("Sales Data Integration", "Integration of sales data from multiple sources")
            ]
            
            for name, description in workflows:
                cursor.execute(
                    "INSERT INTO workflows (name, description) VALUES (%s, %s) RETURNING id",
                    (name, description)
                )
                workflow_id = cursor.fetchone()[0]
                
              
                
                
                # Insert logs
                if name == "Customer Data Migration":
                    logs = [
                        ("Error", "Missing email addresses for 15 customers"),
                        ("Warning", "Duplicate customer IDs found"),
                        ("Info", "Address format inconsistent across records")
                    ]
                elif name == "Product Catalog Transformation":
                    logs = [
                        ("Error", "Invalid price format for 8 products"),
                        ("Warning", "Missing category information for 12 products"),
                        ("Info", "Product names contain special characters")
                    ]
                else:
                    logs = [
                        ("Error", "Date format inconsistent across regions"),
                        ("Warning", "Missing sales representative information"),
                        ("Info", "Currency conversion required for international sales")
                    ]
                
                for log_type, message in logs:
                    cursor.execute(
                        "INSERT INTO workflow_logs (workflow_id, log_type, message) VALUES (%s, %s, %s)",
                        (workflow_id, log_type, message)
                    )
            
            conn.commit()
            print("Sample data inserted successfully")
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error inserting sample data: {e}")
    finally:
        if conn:
            release_connection(conn)

