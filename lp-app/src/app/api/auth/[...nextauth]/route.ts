import NextAuth from "next-auth";
import SlackProvider from "next-auth/providers/slack";

const handler = NextAuth({
  providers: [
    SlackProvider({
      clientId: process.env.SLACK_CLIENT_ID || "",
      clientSecret: process.env.SLACK_CLIENT_SECRET || "",
    }),
  ],
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async session({ session, token }) {
      // Attach Slack user info to session
      if (token.sub) {
        (session as any).userId = token.sub;
      }
      if (token.picture) {
        session.user = { ...session.user, image: token.picture as string };
      }
      return session;
    },
    async jwt({ token, profile }) {
      if (profile) {
        token.slackId = (profile as any).sub;
      }
      return token;
    },
  },
  secret: process.env.NEXTAUTH_SECRET || "marketprobe-dev-secret-change-in-prod",
});

export { handler as GET, handler as POST };
