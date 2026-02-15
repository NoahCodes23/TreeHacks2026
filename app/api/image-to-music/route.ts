import { NextRequest } from 'next/server';

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:3000';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const response = await fetch(`${API_BASE_URL}/image-to-music`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    return Response.json(data, { status: response.status });
  } catch (error) {
    console.error('Error calling image-to-music API:', error);
    return Response.json(
      { error: 'Failed to generate music' },
      { status: 500 }
    );
  }
}
