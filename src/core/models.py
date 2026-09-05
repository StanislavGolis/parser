from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Board(Base):
    __tablename__ = "boards"
    
    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False)
    name = Column(String(100))
    last_parsed_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class Thread(Base):
    __tablename__ = "threads"
    
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"))
    thread_id = Column(Integer, nullable=False)  # Внешний ID треда
    title = Column(String(500))
    created_at = Column(DateTime)
    last_updated = Column(DateTime)
    is_active = Column(Boolean, default=True)

class MediaFile(Base):
    __tablename__ = "media_files"
    
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"))
    thread_id = Column(Integer, ForeignKey("threads.id"))
    
    # Внешние ID
    thread_external_id = Column(Integer)  # ID треда на дваче
    post_external_id = Column(Integer)    # ID поста на дваче
    
    # Информация о файле
    original_filename = Column(String(255))
    file_hash = Column(String(64))  # SHA256
    file_size = Column(BigInteger)
    
    # Путь в хранилище (относительный)
    storage_path = Column(String(500))
    thumbnail_path = Column(String(500))  # Для видео
    
    # Тип
    file_type = Column(String(10))  # 'image' или 'video'
    mime_type = Column(String(100))
    
    # Статус
    status = Column(String(20), default='downloaded')  # 'downloaded', 'processed', 'failed'
    
    # Метаданные (для будущих AI фич)
    ai_description = Column(Text, nullable=True)
    ai_tags = Column(Text, nullable=True)  # JSON строка
    ai_processed = Column(Boolean, default=False)
    
    parsed_at = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, default=0)