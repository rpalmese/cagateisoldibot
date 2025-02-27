# -*- coding: utf-8 -*-
import os
import Utils
import telebot
import logging
import Settings
import Keyboards
import Statements

from datetime import datetime
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler

# Check for database file
if not (os.path.isfile(Settings.DATABASE)):
    print("Database not found!")
    exit(-1)

# Check for token
if Settings.API_TOKEN == '' or Settings.API_TOKEN == "INSERT_TOKEN_HERE":
    print("Token invalid!")
    exit(-1)

# Create a logger, then set its level to DEBUG (alternatively, INFO)
logger = telebot.logger
telebot.logger.setLevel(logging.DEBUG)
# Create bot obj with token in settings file
bot = telebot.TeleBot(Settings.API_TOKEN)

# Notify group when is time to pay!
def paymentNotify(group_id):
    if Settings.DEBUG: return Utils.__resetPayments(group_id,bot)
    expiration = Utils.getExpiration(group_id)
    for user in Utils.getAllUsers(group_id):
        Utils.newPayment(expiration,group_id,user)
    bot.send_message(group_id,Statements.IT.TimeToPay.replace("$$",Utils.moneyEach(group_id)),reply_markup=Keyboards.buildKeyboardForPayment(group_id,[0,0,0,0]),parse_mode='markdown')

# APScheduler background object
scheduler = BackgroundScheduler()
# List of all scheduled job
jobScheduledList = []
# Get trigger from db and load into memory
results = Utils.getTriggers()
for trigger in results:
    jobScheduledList.append(scheduler.add_job(paymentNotify,CronTrigger('*','*',trigger[2],hour=8,minute=00),[trigger[1]]))
# Start the scheduler
scheduler.start()

# Bot added in a group (also during group's creation)
@bot.message_handler(content_types=["group_chat_created","new_chat_members"])
def added_in_a_group(message):
    # Send start message, with start keyboard and save the message id into database
    msg_id = bot.send_message(message.chat.id,Statements.IT.Start.replace('$$',message.from_user.first_name),reply_markup=Keyboards.Start,parse_mode='markdown').message_id
    # Create an half-empty record for the new group
    Utils.executeQuery("INSERT INTO GROUPS(GROUP_ID,START_MSG_ID,ADMIN_ID) VALUES(?,?,?)",[message.chat.id,msg_id,message.from_user.id])

# Received start command
@bot.message_handler(commands=['start'])
def start(message):
    # If is a group chat
    if message.chat.type == 'group' or message.chat.type == 'supergroup':
        # If the group not already exists in db
        if not Utils.groupAlreadyExists(message.chat.id):
            # Send start message, with start keyboard and save the message id into database
            msg_id = bot.send_message(message.chat.id,Statements.IT.Start.replace('$$',message.from_user.first_name),reply_markup=Keyboards.Start,parse_mode='markdown').message_id
            # Create an half-empty record for the new group            
            Utils.executeQuery("INSERT INTO GROUPS(GROUP_ID,START_MSG_ID,ADMIN_ID) VALUES(?,?,?)",[message.chat.id,msg_id,message.from_user.id])
        else:
            # If START_MSG_ID == -1 then the group was already configured
            if Utils.getMessageID(message.chat.id) == -1:
                bot.send_message(message.chat.id,Statements.IT.AlreadyConfigured,reply_markup=Keyboards.Reset,parse_mode='markdown')
            else:
                # Reply to the first start message
                bot.send_message(message.chat.id,Statements.IT.UseThis,reply_to_message_id=Utils.getMessageID(message.chat.id),parse_mode='markdown',reply_markup=Keyboards.Reset)
    # Else if is a private chat
    elif message.chat.type == 'private':
        bot.send_message(message.chat.id,Statements.IT.Welcome.replace('$$',message.from_user.first_name),parse_mode='markdown',reply_markup=Keyboards.StartPrivate,disable_web_page_preview=True)

# User that tap on 'I Use Netflix' button and join the bot
@bot.callback_query_handler(func=lambda call: call.data == 'iusenetflix')
def addMember(call):
    # Max reached 
    if Utils.countNetflixers(call.message.chat.id) == 4:
        bot.answer_callback_query(call.id,Statements.IT.MaxReached,show_alert=True)
    # Duplicated user
    elif call.from_user.first_name in Utils.listNetflixers(call.message.chat.id):
        bot.answer_callback_query(call.id,Statements.IT.AlreadySigned,show_alert=True)
    else:
        # Add user in USERS table
        Utils.executeQuery("INSERT INTO USERS(GROUP_ID,CHAT_ID,USERNAME,FIRST_NAME) VALUES (?,?,?,?)",[call.message.chat.id,call.from_user.id,call.from_user.username,call.from_user.first_name])
        # Update record in GROUPS table, increment number of user joined
        Utils.executeQuery("UPDATE GROUPS SET NETFLIXERS=NETFLIXERS+1 WHERE GROUP_ID=?",[call.message.chat.id])
        # Create an updated keyboard with new member
        updatedKeyboard = Keyboards.buildKeyboardForUser(call.message.chat.id)
        #updatedKeyboard = Keyboards.buildKeyboardForUser(Utils.listNetflixers(call.message.chat.id))
        # Edit the keyboard markup of the same message
        bot.edit_message_reply_markup(chat_id=call.message.chat.id,message_id=call.message.message_id,reply_markup=updatedKeyboard)
        # Answer to the callback
        bot.answer_callback_query(call.id,Statements.IT.Added)

# Remove user that already tapped 'I Use Netflix' button
@bot.callback_query_handler(func=lambda call: 'remove_' in call.data)
def removeUser(call):
    # If id of the user is different from id the user in button
    if int(call.from_user.id) != int(call.data[7:]):
        bot.answer_callback_query(call.id,Statements.IT.NotPermitted,show_alert=True,cache_time=10)
    else:
        # Delete user from db
        Utils.executeQuery("DELETE FROM USERS WHERE CHAT_ID=? AND GROUP_ID=?",[call.from_user.id,call.message.chat.id])
        # Decrement counter in GROUPS table
        Utils.executeQuery("UPDATE GROUPS SET NETFLIXERS=NETFLIXERS - 1 WHERE GROUP_ID=?",[call.message.chat.id])
        # Create an updated keyboard
        updatedKeyboard = Keyboards.buildKeyboardForUser(call.message.chat.id)
        #updatedKeyboard = Keyboards.buildKeyboardForUser(Utils.listNetflixers(call.message.chat.id))
        # Edit keyboard markup in the same message
        bot.edit_message_reply_markup(chat_id=call.message.chat.id,message_id=call.message.message_id,reply_markup=updatedKeyboard)
        # Answer to the callback
        bot.answer_callback_query(call.id,Statements.IT.Removed)

# Confirm netflixers's list
@bot.callback_query_handler(func=lambda call: call.data == 'hereweare')
def hereweare(call):
    # If user is not admin
    if call.from_user.id != Utils.getAdminID(call.message.chat.id):
        bot.answer_callback_query(call.id,Statements.IT.NotAdmin,show_alert=True,cache_time=10)
    else:
        # If there aren't netflixers
        if Utils.countNetflixers(call.message.chat.id) == 0:
            bot.answer_callback_query(call.id,Statements.IT.AtLeastOneUser,show_alert=True)
        else:
            netflixers = ''
            # Create an updated list of netflixers
            for index, user in enumerate(Utils.listNetflixers(call.message.chat.id)):
                netflixers += "{} {}\n".format(Keyboards.Numbers[index],user)
            # Update the same message with a new list 
            bot.edit_message_text(chat_id=call.message.chat.id,message_id=call.message.message_id,text="{}\n\n*{}*".format(Statements.IT.ConfirmList,netflixers),reply_markup=Keyboards.Confirm,parse_mode='markdown')
            bot.answer_callback_query(call.id,Statements.IT.AlmostDone,cache_time=5)

# Handler for general 'yes' callback
@bot.callback_query_handler(func=lambda call: call.data == 'yes')
def yes(call):
    # If user is not admin
    if call.from_user.id != Utils.getAdminID(call.message.chat.id):
        bot.answer_callback_query(call.id,Statements.IT.NotAdmin,show_alert=True,cache_time=10)
    else:
        # Netflixers's list confirmation 
        if call.message.text[:34] == Statements.IT.ConfirmList:
            bot.edit_message_text(Statements.IT.Schedule,call.message.chat.id,call.message.message_id,reply_markup=Keyboards.DateKeyboard,parse_mode='markdown')
        # Expiration's date confirmation
        elif call.message.text[:-4] == Statements.IT.ConfirmSchedule[:-6] or call.message.text[:-3] == Statements.IT.ConfirmSchedule[:-6]:
            # Save expiration date in a var
            Expiration = ''.join(i for i in call.message.text if i.isdigit())
            # Update expiration date into db            
            Utils.executeQuery("UPDATE GROUPS SET EXPIRATION=? WHERE GROUP_ID=?",[Expiration,call.message.chat.id])
            netflixers = ''
            # Create an updated list
            for index, user in enumerate(Utils.listNetflixers(call.message.chat.id)):
                netflixers += "{} {}\n".format(Keyboards.Numbers[index],user)
            # Edit message text with new list
            bot.edit_message_text(Statements.IT.Done.replace('$$',netflixers,1).replace('$$',Expiration),call.message.chat.id,call.message.message_id,reply_markup={},parse_mode='markdown')
            # Edit START_MSG_ID into db, set to -1 that mean 'group already configured'
            Utils.executeQuery("UPDATE GROUPS SET START_MSG_ID=-1 WHERE GROUP_ID=?",[call.message.chat.id])
            # Add a new scheduled job for the group, on expiration day of every month at 08:00 AM
            job = scheduler.add_job(paymentNotify,CronTrigger('*','*',int(Expiration),hour=8,minute=00),[call.message.chat.id])
            # Append job object in jobScheduledList 
            jobScheduledList.append(job)
            # Save trigger into db
            Utils.saveTrigger(job.id,call.message.chat.id,Expiration)
        # Reset confiration
        elif call.message.text == Statements.IT.ConfirmReset.replace('*','',2):
            # Delete information from db, PAYMENTS and USERS tables
            Utils.executeQuery("DELETE FROM PAYMENTS WHERE GROUP_ID=? AND EXPIRATION=?",[call.message.chat.id,Utils.getExpiration(call.message.chat.id)])
            Utils.executeQuery("DELETE FROM USERS WHERE GROUP_ID=?",[call.message.chat.id])
            
            # Get trigger ID from db
            triggerID = Utils.getTriggerID(call.message.chat.id)
            # Remove trigger from scheduled job
            for index,job in enumerate(jobScheduledList):
                if job.id == triggerID:
                    jobScheduledList.pop(index)
                    break
            # Delete information from db, TRIGGER and GROUPS tables
            Utils.executeQuery("DELETE FROM TRIGGER WHERE TRIGGER_ID=?",[triggerID])
            Utils.executeQuery("DELETE FROM GROUPS WHERE GROUP_ID=?",[call.message.chat.id])

            # Edit message with NewConfig statements
            bot.edit_message_text(Statements.IT.NewConfig,call.message.chat.id,call.message.message_id,reply_markup={},parse_mode='markdown')
            # Answer with a sucess message
            bot.answer_callback_query(call.id,Statements.IT.Resetted,show_alert=True,cache_time=10)

# Handler for general 'no' callback
@bot.callback_query_handler(func=lambda call: call.data == 'no')
def no(call):
    # If user is not admin
    if call.from_user.id != Utils.getAdminID(call.message.chat.id):
        bot.answer_callback_query(call.id,Statements.IT.NotAdmin,show_alert=True,cache_time=10)
    else:
        # If callback is coming from list's confirmation message
        if call.message.text[:34] == Statements.IT.ConfirmList:
            bot.edit_message_text(Statements.IT.Start.replace('$$',call.from_user.first_name),call.message.chat.id,call.message.message_id,reply_markup=Keyboards.buildKeyboardForUser(call.message.chat.id),parse_mode='markdown')
        # If callback is coming from expiration's confirmation message
        elif call.message.text[:-4] == Statements.IT.ConfirmSchedule[:-6]:
            bot.edit_message_text(Statements.IT.Schedule,call.message.chat.id,call.message.message_id,reply_markup=Keyboards.DateKeyboard,parse_mode='markdown')
        # If callback is coming from reset's confirmation message        
        elif call.message.text == Statements.IT.ConfirmReset.replace('*','',2):
            bot.edit_message_text(Statements.IT.AlreadyConfigured,call.message.chat.id,call.message.message_id,reply_markup=Keyboards.Reset,parse_mode='markdown')

# Expiration date confirmation
@bot.callback_query_handler(func=lambda call: 'date_' in call.data)
def confirmExpiration(call):
    # If user is not admin
    if call.from_user.id != Utils.getAdminID(call.message.chat.id):
        bot.answer_callback_query(call.id,Statements.IT.NotAdmin,show_alert=True,cache_time=10)
    else:
        bot.edit_message_text(Statements.IT.ConfirmSchedule.replace('$$',call.data[5:]),call.message.chat.id,call.message.message_id,reply_markup=Keyboards.Confirm,parse_mode='markdown')

# When user tap on his name in payment list
@bot.callback_query_handler(func=lambda call: 'payed_' in call.data)
def payed(call):
    # Get current status of the user from db
    stato = Utils.getStatus(call.message.chat.id,Utils.getExpiration(call.message.chat.id),call.data[6:])
    # If the user has already payed
    if stato == 1:
        bot.answer_callback_query(call.id,Statements.IT.AlreadyPayed.replace('$$',Utils.getUser(call.message.chat.id,call.data[6:])[2]),show_alert=True)
    else:
        # If name is different and is not admin
        if int(call.from_user.id) != int(call.data[6:]) and call.from_user.id != Utils.getAdminID(call.message.chat.id):
            bot.answer_callback_query(call.id,Statements.IT.NotPermitted,show_alert=True,cache_time=10)
            return
        # If the user is not the admin, the payment's status is set to -1, mean 'waiting for admin confirm'
        elif int(call.from_user.id) == int(call.data[6:]) and int(call.from_user.id) != Utils.getAdminID(call.message.chat.id):
                # If user is waiting for confirmation
                if Utils.getStatus(call.message.chat.id,Utils.getExpiration(call.message.chat.id),call.from_user.id) == -1:
                    bot.answer_callback_query(call.id,Statements.IT.IsWaiting,show_alert=True,cache_time=10)
                    return
                else:
                    # Otherwise set user's status to -1, wait for confirmation
                    Utils.executeQuery("UPDATE PAYMENTS SET STATUS=-1 WHERE GROUP_ID=? AND CHAT_ID=? AND EXPIRATION=?",[call.message.chat.id,call.data[6:],Utils.getExpiration(call.message.chat.id)])        
                    bot.answer_callback_query(call.id,Statements.IT.WaitingFor,show_alert=True,cache_time=10)
        # If is admin
        elif int(call.from_user.id) == Utils.getAdminID(call.message.chat.id):
            # Update payment status into db to payed
            Utils.executeQuery("UPDATE PAYMENTS SET STATUS=1 WHERE GROUP_ID=? AND CHAT_ID=? AND EXPIRATION=?",[call.message.chat.id,call.data[6:],Utils.getExpiration(call.message.chat.id)])
            if int(call.from_user.id) != int(call.data[6:]):
                username = "@{}".format(str(Utils.getUser(call.message.chat.id,call.data[6:])[1]))
                if not username:
                    username = Utils.getUser(call.message.chat.id,call.data[6:])[2]
                bot.send_message(call.message.chat.id,Statements.IT.PaymentAccepted.replace('$$',username),parse_mode='markdown')
            # Get current status of all users
            results = Utils.getAllStatus(call.message.chat.id,Utils.getExpiration(call.message.chat.id))
            everyonePayed = True
            for status in results:
                if status != 1:                
                    everyonePayed = False
            # If everyone has already payed
            if everyonePayed:
                bot.edit_message_text(Statements.IT.EveryonePaid.replace('$$',Utils.newExpiration(Utils.getExpiration(call.message.chat.id))),call.message.chat.id,call.message.message_id,reply_markup={},parse_mode='markdown')
                return
        # Get current status of all users
        status = Utils.getAllStatus(call.message.chat.id,Utils.getExpiration(call.message.chat.id))
        # Create an update keyboard with new status
        kb = Keyboards.buildKeyboardForPayment(call.message.chat.id,status)
        # Edit message markup with updated keyboard
        bot.edit_message_reply_markup(chat_id=call.message.chat.id,message_id=call.message.message_id,reply_markup=kb)

# Reset current group's configuration 
@bot.callback_query_handler(func=lambda call: call.data == 'reset')
def reset(call):
    # If user is not the admin
    if call.from_user.id != Utils.getAdminID(call.message.chat.id):
        bot.answer_callback_query(call.id,Statements.IT.NotAdmin,show_alert=True,cache_time=10)
    else:
        bot.edit_message_text(Statements.IT.ConfirmReset,call.message.chat.id,call.message.message_id,reply_markup=Keyboards.Confirm,parse_mode='markdown')

# DEBUG funtion that fire paymentNotify trigger 
@bot.message_handler(commands=['pay'])
def pay(message):
    paymentNotify(message.chat.id)

# DEBUG funtion that trigger sheduled jobs 
@bot.message_handler(commands=['fire'])
def fire(message):
    for job in scheduler.get_jobs():
        job.modify(next_run_time=datetime.now())

@bot.message_handler(func=lambda message: message.text and message.text[2:] == 'Dona')
def donate(message):
    bot.send_message(message.chat.id,Statements.IT.Donate,parse_mode='markdown',disable_web_page_preview=True)

@bot.message_handler(func=lambda message: message.text and message.text[2:] == 'Info')
def about(message):
    bot.send_message(message.chat.id,Statements.IT.About,parse_mode='markdown',disable_web_page_preview=True)

# Put bot in polling state, waiting for incoming message
try:
    bot.polling()
except Exception as e:
    print(e)