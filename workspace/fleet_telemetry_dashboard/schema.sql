-- Initial Schema for Fleet Telemetry
CREATE TABLE vehicles (
    id SERIAL PRIMARY KEY,
    vin VARCHAR(17) UNIQUE NOT NULL,
    model VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE telemetry (
    id SERIAL PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    speed DOUBLE PRECISION,
    fuel_level DOUBLE PRECISION,
    engine_temp DOUBLE PRECISION,
    diagnostics JSONB DEFAULT NULL
);

-- Indexing for performance
CREATE INDEX idx_vehicles_vin ON vehicles(vin);
CREATE INDEX idx_telemetry_vehicle_id ON telemetry(vehicle_id);
CREATE INDEX idx_telemetry_timestamp ON telemetry(timestamp);
