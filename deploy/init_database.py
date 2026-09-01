import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


SCHEMA_STATEMENTS = (
    """
    IF OBJECT_ID(N'dbo.Users', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.Users (
            ID uniqueidentifier NOT NULL CONSTRAINT PK_Users PRIMARY KEY DEFAULT NEWID(),
            UserID nvarchar(100) NOT NULL,
            Name nvarchar(100) NOT NULL,
            Password nvarchar(512) NULL,
            Position nvarchar(50) NOT NULL CONSTRAINT DF_Users_Position DEFAULT N'User',
            Location nvarchar(100) NULL,
            Last_login datetime2 NULL,
            CONSTRAINT UQ_Users_UserID UNIQUE (UserID)
        );
    END
    """,
    """
    IF COL_LENGTH(N'dbo.Users', N'Password') < 512
        ALTER TABLE dbo.Users ALTER COLUMN Password nvarchar(512) NULL
    """,
    """
    IF OBJECT_ID(N'dbo.Documents', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.Documents (
            DocID nvarchar(64) NOT NULL CONSTRAINT PK_Documents PRIMARY KEY,
            User_ID uniqueidentifier NOT NULL,
            OriginalName nvarchar(512) NOT NULL,
            StorageName nvarchar(512) NOT NULL,
            UploadTime datetime2 NOT NULL CONSTRAINT DF_Documents_UploadTime DEFAULT SYSDATETIME(),
            Pages int NOT NULL,
            CONSTRAINT FK_Documents_Users FOREIGN KEY (User_ID) REFERENCES dbo.Users(ID)
        );
    END
    """,
    """
    IF OBJECT_ID(N'dbo.DocVersion', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.DocVersion (
            ID nvarchar(64) NOT NULL CONSTRAINT PK_DocVersion PRIMARY KEY,
            FileName nvarchar(512) NOT NULL,
            Author nvarchar(100) NULL,
            Uploader uniqueidentifier NOT NULL,
            Size bigint NOT NULL,
            Pages int NOT NULL,
            Version nvarchar(100) NULL,
            UploadTime datetime2 NOT NULL CONSTRAINT DF_DocVersion_UploadTime DEFAULT SYSDATETIME(),
            CONSTRAINT FK_DocVersion_Users FOREIGN KEY (Uploader) REFERENCES dbo.Users(ID)
        );
    END
    """,
    """
    IF OBJECT_ID(N'dbo.MappingRecord', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.MappingRecord (
            RecordID nvarchar(64) NOT NULL CONSTRAINT PK_MappingRecord PRIMARY KEY,
            OldDocID nvarchar(64) NOT NULL,
            NewDocID nvarchar(64) NOT NULL,
            Creator uniqueidentifier NOT NULL,
            Status int NOT NULL CONSTRAINT DF_MappingRecord_Status DEFAULT 0,
            IsPublish bit NOT NULL CONSTRAINT DF_MappingRecord_IsPublish DEFAULT 0,
            CreateTime datetime2 NOT NULL CONSTRAINT DF_MappingRecord_CreateTime DEFAULT SYSDATETIME(),
            CONSTRAINT FK_MappingRecord_OldDoc FOREIGN KEY (OldDocID) REFERENCES dbo.DocVersion(ID),
            CONSTRAINT FK_MappingRecord_NewDoc FOREIGN KEY (NewDocID) REFERENCES dbo.DocVersion(ID),
            CONSTRAINT FK_MappingRecord_Users FOREIGN KEY (Creator) REFERENCES dbo.Users(ID)
        );
    END
    """,
    """
    IF OBJECT_ID(N'dbo.NoteTransferHistory', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.NoteTransferHistory (
            TransferID nvarchar(64) NOT NULL CONSTRAINT PK_NoteTransferHistory PRIMARY KEY,
            UserID uniqueidentifier NOT NULL,
            MappingID nvarchar(64) NOT NULL,
            SourceFileName nvarchar(512) NOT NULL,
            ResultName nvarchar(512) NOT NULL,
            CreateTime datetime2 NOT NULL CONSTRAINT DF_NoteTransferHistory_CreateTime DEFAULT SYSDATETIME(),
            CONSTRAINT FK_NoteTransferHistory_Users FOREIGN KEY (UserID) REFERENCES dbo.Users(ID),
            CONSTRAINT FK_NoteTransferHistory_MappingRecord FOREIGN KEY (MappingID) REFERENCES dbo.MappingRecord(RecordID)
        );
    END
    """,
    """
    IF OBJECT_ID(N'dbo.BackgroundTasks', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.BackgroundTasks (
            TaskID nvarchar(64) NOT NULL CONSTRAINT PK_BackgroundTasks PRIMARY KEY,
            TaskType varchar(30) NOT NULL,
            UserID uniqueidentifier NOT NULL,
            Status varchar(20) NOT NULL CONSTRAINT DF_BackgroundTasks_Status DEFAULT 'QUEUED',
            PayloadJson nvarchar(max) NOT NULL,
            ErrorMessage nvarchar(max) NULL,
            Attempts int NOT NULL CONSTRAINT DF_BackgroundTasks_Attempts DEFAULT 0,
            CreatedAt datetimeoffset(7) NOT NULL CONSTRAINT DF_BackgroundTasks_CreatedAt DEFAULT SYSDATETIMEOFFSET(),
            StartedAt datetimeoffset(7) NULL,
            FinishedAt datetimeoffset(7) NULL,
            CONSTRAINT CK_BackgroundTasks_Type CHECK (TaskType IN ('mapping', 'migration')),
            CONSTRAINT CK_BackgroundTasks_Status CHECK (Status IN ('QUEUED', 'PROCESSING', 'SUCCESS', 'ERROR')),
            CONSTRAINT FK_BackgroundTasks_Users FOREIGN KEY (UserID) REFERENCES dbo.Users(ID)
        );
    END
    """,
    """
    IF OBJECT_ID(N'dbo.Audit_logs', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.Audit_logs (
            LogID int IDENTITY(1, 1) NOT NULL CONSTRAINT PK_Audit_logs PRIMARY KEY,
            [Action] varchar(200) NOT NULL,
            CreatedAt datetimeoffset(7) NOT NULL CONSTRAINT DF_Audit_logs_CreatedAt DEFAULT SYSDATETIMEOFFSET(),
            User_id varchar(100) NULL,
            Detail_json varchar(max) NULL,
            Remote_addr varchar(100) NULL
        );
    END
    """,
    """
    IF COL_LENGTH(N'dbo.Audit_logs', N'Action') IS NULL
        ALTER TABLE dbo.Audit_logs ADD [Action] varchar(200) NULL;
    IF COL_LENGTH(N'dbo.Audit_logs', N'User_id') IS NULL
        ALTER TABLE dbo.Audit_logs ADD User_id varchar(100) NULL;
    IF COL_LENGTH(N'dbo.Audit_logs', N'Detail_json') IS NULL
        ALTER TABLE dbo.Audit_logs ADD Detail_json varchar(max) NULL;
    IF COL_LENGTH(N'dbo.Audit_logs', N'Remote_addr') IS NULL
        ALTER TABLE dbo.Audit_logs ADD Remote_addr varchar(100) NULL;

    IF COL_LENGTH(N'dbo.Audit_logs', N'ErrorMessage') IS NOT NULL
        EXEC(N'UPDATE dbo.Audit_logs
              SET [Action] = COALESCE([Action], ''legacy_error''),
                  Detail_json = COALESCE(Detail_json, ErrorMessage, Traceback)
              WHERE [Action] IS NULL OR Detail_json IS NULL;');

    UPDATE dbo.Audit_logs SET [Action] = 'legacy_error' WHERE [Action] IS NULL;
    ALTER TABLE dbo.Audit_logs ALTER COLUMN [Action] varchar(200) NOT NULL;
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_Documents_User_ID'
          AND object_id = OBJECT_ID(N'dbo.Documents')
    )
        CREATE INDEX IX_Documents_User_ID ON dbo.Documents(User_ID)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_DocVersion_Uploader_UploadTime'
          AND object_id = OBJECT_ID(N'dbo.DocVersion')
    )
        CREATE INDEX IX_DocVersion_Uploader_UploadTime ON dbo.DocVersion(Uploader, UploadTime DESC)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_MappingRecord_Creator_CreateTime'
          AND object_id = OBJECT_ID(N'dbo.MappingRecord')
    )
        CREATE INDEX IX_MappingRecord_Creator_CreateTime ON dbo.MappingRecord(Creator, CreateTime DESC)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_NoteTransferHistory_UserID'
          AND object_id = OBJECT_ID(N'dbo.NoteTransferHistory')
    )
        CREATE INDEX IX_NoteTransferHistory_UserID ON dbo.NoteTransferHistory(UserID, CreateTime DESC)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_BackgroundTasks_Status_CreatedAt'
          AND object_id = OBJECT_ID(N'dbo.BackgroundTasks')
    )
        CREATE INDEX IX_BackgroundTasks_Status_CreatedAt ON dbo.BackgroundTasks(Status, CreatedAt, TaskID)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_BackgroundTasks_UserID_Status'
          AND object_id = OBJECT_ID(N'dbo.BackgroundTasks')
    )
        CREATE INDEX IX_BackgroundTasks_UserID_Status ON dbo.BackgroundTasks(UserID, Status, CreatedAt DESC)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_Audit_logs_CreatedAt'
          AND object_id = OBJECT_ID(N'dbo.Audit_logs')
    )
        CREATE INDEX IX_Audit_logs_CreatedAt ON dbo.Audit_logs(CreatedAt DESC)
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_Audit_logs_User_id_CreatedAt'
          AND object_id = OBJECT_ID(N'dbo.Audit_logs')
    )
        CREATE INDEX IX_Audit_logs_User_id_CreatedAt ON dbo.Audit_logs(User_id, CreatedAt DESC)
    """,
)


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required in .env")

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(text(statement))

    print("Database schema is ready.")


if __name__ == "__main__":
    main()
