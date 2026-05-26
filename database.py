import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Tuple


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                thread_id INTEGER,
                thread_name TEXT,
                user_id INTEGER,
                username TEXT,
                custom_title TEXT,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                summarized INTEGER DEFAULT 0,
                UNIQUE(chat_id, message_id)
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_chat_thread 
            ON messages(chat_id, thread_id, timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_summarized 
            ON messages(chat_id, thread_id, summarized, timestamp)
        ''')
        
        conn.commit()
        conn.close()
    
    def add_message(self, chat_id: int, message_id: int, thread_id: Optional[int], 
                    thread_name: Optional[str], user_id: int, username: Optional[str], 
                    custom_title: Optional[str], text: str):
        """Add a message to the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO messages 
                (chat_id, message_id, thread_id, thread_name, user_id, username, custom_title, text, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, message_id, thread_id, thread_name, user_id, username, custom_title, text, datetime.now()))
            
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
        finally:
            conn.close()
    
    def get_unsummarized_messages(self, chat_id: int, thread_id: Optional[int], 
                                  limit: int) -> List[Tuple]:
        """Get unsummarized messages from a chat or thread"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id is not None:
            cursor.execute('''
                SELECT id, username, custom_title, text, timestamp, thread_id, thread_name
                FROM messages 
                WHERE chat_id = ? AND thread_id = ? AND summarized = 0
                ORDER BY timestamp ASC
                LIMIT ?
            ''', (chat_id, thread_id, limit))
        else:
            cursor.execute('''
                SELECT id, username, custom_title, text, timestamp, thread_id, thread_name
                FROM messages 
                WHERE chat_id = ? AND thread_id IS NULL AND summarized = 0
                ORDER BY timestamp ASC
                LIMIT ?
            ''', (chat_id, limit))
        
        messages = cursor.fetchall()
        conn.close()
        
        return messages
    
    def get_all_unsummarized_messages(self, chat_id: int, limit: int) -> List[Tuple]:
        """Get all unsummarized messages from a chat (all threads combined)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, custom_title, text, timestamp, thread_id, thread_name
            FROM messages 
            WHERE chat_id = ? AND summarized = 0
            ORDER BY thread_id, timestamp ASC
            LIMIT ?
        ''', (chat_id, limit))
        
        messages = cursor.fetchall()
        conn.close()
        
        return messages
    
    def delete_messages(self, message_ids: List[int]):
        """Delete messages by IDs"""
        if not message_ids:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        placeholders = ','.join('?' * len(message_ids))
        cursor.execute(f'''
            DELETE FROM messages 
            WHERE id IN ({placeholders})
        ''', message_ids)
        
        conn.commit()
        conn.close()
