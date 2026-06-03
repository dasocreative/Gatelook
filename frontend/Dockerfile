FROM node:20-slim

WORKDIR /app

# Copy dependency mappings
COPY package.json ./

# Install npm modules
RUN npm install

# Copy source tree
COPY . .

# Expose Vite dev port
EXPOSE 5173

# Boot development compilation server with direct host mapping
CMD ["npm", "run", "dev"]
