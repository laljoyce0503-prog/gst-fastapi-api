require('dotenv').config();
const express = require('express');
const mysql = require('mysql2');
const cors = require('cors');

const app = express();
const port = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json()); // Parses incoming JSON requests

// Database Connection
const db = mysql.createPool({
    host: 'localhost',      // Change if your DB is hosted elsewhere
    user: 'root',           // Your MySQL username
    password: 'Joyce@0503',   // Your MySQL password
    database: 'gst_db',
    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0
});

// Check connection
db.getConnection((err, connection) => {
    if (err) {
        console.error('Error connecting to MySQL:', err.message);
    } else {
        console.log('Connected to MySQL database: gst_db');
        connection.release();
    }
});

// --- ROUTES ---

// 1. GET ALL: Retrieve all submissions
app.get('/api/submissions', (req, res) => {
    const query = 'SELECT * FROM vueform_sub';
    db.query(query, (err, results) => {
        if (err) return res.status(500).json({ error: err.message });
        
        // Parse form_data string back to JSON for the client
        const parsedResults = results.map(row => ({
            ...row,
            form_data: JSON.parse(row.form_data || '{}')
        }));
        
        res.json(parsedResults);
    });
});

// 2. GET ONE: Retrieve a single submission by ID
app.get('/api/submissions/:id', (req, res) => {
    const query = 'SELECT * FROM vueform_sub WHERE id = ?';
    db.query(query, [req.params.id], (err, results) => {
        if (err) return res.status(500).json({ error: err.message });
        if (results.length === 0) return res.status(404).json({ message: 'Submission not found' });

        const row = results[0];
        row.form_data = JSON.parse(row.form_data || '{}');
        res.json(row);
    });
});

// 3. POST: Create a new submission
app.post('/api/submissions', (req, res) => {
    const { form_key, form_data } = req.body;

    // Validate input
    if (!form_key || !form_data) {
        return res.status(400).json({ message: 'form_key and form_data are required' });
    }

    // Stringify form_data to store in LONGTEXT column
    const formDataString = JSON.stringify(form_data);

    const query = 'INSERT INTO vueform_sub (form_key, form_data) VALUES (?, ?)';
    db.query(query, [form_key, formDataString], (err, result) => {
        if (err) return res.status(500).json({ error: err.message });
        res.status(201).json({ id: result.insertId, message: 'Submission created successfully' });
    });
});

// 4. PUT: Update an existing submission
app.put('/api/submissions/:id', (req, res) => {
    const { form_key, form_data } = req.body;
    const formDataString = JSON.stringify(form_data);

    const query = 'UPDATE vueform_sub SET form_key = ?, form_data = ? WHERE id = ?';
    db.query(query, [form_key, formDataString, req.params.id], (err, result) => {
        if (err) return res.status(500).json({ error: err.message });
        if (result.affectedRows === 0) return res.status(404).json({ message: 'Submission not found' });
        res.json({ message: 'Submission updated successfully' });
    });
});

// 5. DELETE: Remove a submission
app.delete('/api/submissions/:id', (req, res) => {
    const query = 'DELETE FROM vueform_sub WHERE id = ?';
    db.query(query, [req.params.id], (err, result) => {
        if (err) return res.status(500).json({ error: err.message });
        if (result.affectedRows === 0) return res.status(404).json({ message: 'Submission not found' });
        res.json({ message: 'Submission deleted successfully' });
    });
});

// Start Server
app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}`);
});