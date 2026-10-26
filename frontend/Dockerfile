FROM node:20-alpine

WORKDIR /app

# Copy package descriptors for layer caching
COPY package*.json ./
RUN npm install

# Copy application source code
COPY . .

# Expose Vite development server port
EXPOSE 5173

# Start Vite dev server bound to 0.0.0.0
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
