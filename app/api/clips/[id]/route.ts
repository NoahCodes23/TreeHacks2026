import { NextRequest } from 'next/server';

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:3000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    const response = await fetch(`${API_BASE_URL}/clips/${id}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    return Response.json(data, { status: response.status });
  } catch (error) {
    console.error('Error fetching clip status:', error);
    return Response.json(
      { error: 'Failed to fetch clip status' },
      { status: 500 }
    );
  }
}

