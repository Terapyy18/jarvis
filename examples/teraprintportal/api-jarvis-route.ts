// TeraPrintPortal → Jarvis bridge route.
// Install as: src/app/api/jarvis/route.ts
//
// Read-only, key-protected endpoint for the Jarvis `teraPrintPortal` tool.
// Auth: the `x-api-key` request header must match the JARVIS_API_KEY
// environment variable. Sensitive columns (invitation tokens, Stripe ids,
// Clerk ids) are never selected.

import { timingSafeEqual } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getDashboardData } from "@/lib/dashboard";

const MAX_ROWS = 100;

function isAuthorised(request: NextRequest): boolean {
  const expected = process.env.JARVIS_API_KEY;
  const provided = request.headers.get("x-api-key");
  if (!expected || !provided) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(provided);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function GET(request: NextRequest) {
  if (!isAuthorised(request)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const resource = request.nextUrl.searchParams.get("resource") ?? "dashboard";

  switch (resource) {
    case "dashboard":
      return NextResponse.json(await getDashboardData());

    case "clients":
      return NextResponse.json(
        await prisma.client.findMany({
          orderBy: { createdAt: "desc" },
          take: MAX_ROWS,
          select: {
            name: true, email: true, company: true, phone: true,
            city: true, isActive: true, createdAt: true,
          },
        }),
      );

    case "projects":
      return NextResponse.json(
        await prisma.project.findMany({
          orderBy: { updatedAt: "desc" },
          take: MAX_ROWS,
          select: {
            name: true, status: true, budget: true, paidAmount: true,
            progressPercent: true, startDate: true, endDate: true,
            client: { select: { name: true } },
          },
        }),
      );

    case "quotes":
      return NextResponse.json(
        await prisma.quote.findMany({
          orderBy: { createdAt: "desc" },
          take: MAX_ROWS,
          select: {
            title: true, amount: true, currency: true, status: true,
            validUntil: true, acceptedAt: true,
            client: { select: { name: true } },
          },
        }),
      );

    case "invoices":
      return NextResponse.json(
        await prisma.invoice.findMany({
          orderBy: { issuedDate: "desc" },
          take: MAX_ROWS,
          select: {
            number: true, amount: true, currency: true, status: true,
            issuedDate: true, dueDate: true,
            client: { select: { name: true } },
            project: { select: { name: true } },
          },
        }),
      );

    case "payments":
      return NextResponse.json(
        await prisma.payment.findMany({
          orderBy: { paymentDate: "desc" },
          take: MAX_ROWS,
          select: {
            amount: true, paymentDate: true, method: true,
            client: { select: { name: true } },
            invoice: { select: { number: true } },
          },
        }),
      );

    case "appointments":
      return NextResponse.json(
        await prisma.appointment.findMany({
          orderBy: { scheduledAt: "desc" },
          take: MAX_ROWS,
          select: {
            scheduledAt: true, durationMinutes: true, status: true,
            notes: true,
            client: { select: { name: true } },
          },
        }),
      );

    case "sales":
      return NextResponse.json(
        await prisma.sale.findMany({
          orderBy: { soldAt: "desc" },
          take: MAX_ROWS,
          select: {
            platform: true, title: true, amount: true, fees: true,
            shippingCost: true, saleType: true, status: true,
            soldAt: true, buyerName: true,
          },
        }),
      );

    case "subscriptions":
      return NextResponse.json(
        await prisma.subscription.findMany({
          orderBy: { createdAt: "desc" },
          take: MAX_ROWS,
          select: {
            label: true, status: true, amount: true, currency: true,
            interval: true, currentPeriodEnd: true, cancelAtPeriodEnd: true,
            client: { select: { name: true } },
          },
        }),
      );

    default:
      return NextResponse.json(
        { error: `Unknown resource '${resource}'` },
        { status: 400 },
      );
  }
}
